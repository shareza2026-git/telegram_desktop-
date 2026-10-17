import asyncio
from collections import OrderedDict
from contextlib import suppress
import logging
import mimetypes
from datetime import datetime, timezone
from pathlib import Path
import time
from typing import Any

from pydantic import SecretStr

from telethon import TelegramClient, events, functions, types, utils
from telethon.sessions import MemorySession, SQLiteSession
from telethon.errors import (
    FileReferenceExpiredError,
    FloodWaitError,
    PasswordHashInvalidError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    PhoneNumberInvalidError,
    SessionPasswordNeededError,
)

from app.config import Settings
from app.models import (
    ApiConfigRequest,
    ChatInfo,
    ClientStatus,
    DeviceSession,
    DesktopError,
    Dialog,
    DialogFolder,
    MediaInfo,
    Message,
    ReactionSummary,
    RecentMediaItem,
)
from app.storage import ChatStore
from app.telegram import convert
from app.telegram.client import build_client
from app.telegram.media import DownloadedMedia, media_path, safe_media_name
from app.telegram.profile import chat_photo_path, is_fresh_chat_photo
from app.telegram.portable import remove_account_from_portable, sync_account_to_portable
from app.telegram.session import SessionManager
from app.telegram.session_import import SessionImporter
from app.telegram.transport import ProxyRoute, TransportCatalog
from app.telegram.transfer_bundle import TransferBundle


logger = logging.getLogger(__name__)

MESSAGE_CACHE_LIMIT = 4000
DIALOG_SNAPSHOT_MAX_AGE = 60.0
# Back-to-back live list requests (startup, reconnect) reuse one fetch.
DIALOG_REUSE_SECONDS = 10.0
NO_PHOTO_RETRY_SECONDS = 6 * 60 * 60
AVATAR_MAX_AGE_SECONDS = 24 * 60 * 60
# In-chat photos use the smallest Telegram size at least this wide, the same
# one Telegram Desktop shows in a bubble; the original is only for downloads.
CHAT_PHOTO_PREVIEW_SIDE = 800


CONNECTION_UNAVAILABLE = "اتصال به تلگرام برقرار نیست؛ تنظیمات پراکسی را بررسی کنید."
CONNECTION_DROPPED = "اتصال به تلگرام قطع شد؛ دوباره تلاش کنید یا پراکسی دیگری انتخاب کنید."


class MediaUnavailable(DesktopError):
    """The requested photo or file does not exist (reported as HTTP 404)."""


class EventBroker:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue] = set()

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=2000)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    async def publish(self, packet: dict) -> None:
        for queue in tuple(self._subscribers):
            try:
                queue.put_nowait(packet)
            except asyncio.QueueFull:
                # A slow client fell behind: drop its backlog and tell it to
                # reload, but keep it subscribed so live updates continue.
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait({"type": "RESYNC", "data": {}})


class TelegramDesktopService:
    def __init__(
        self,
        settings: Settings,
        store: ChatStore,
        transport: TransportCatalog,
    ) -> None:
        self.settings = settings
        self.store = store
        self.transport = transport
        self.transfer_bundle = TransferBundle(settings, transport)
        self.sessions = SessionManager(settings)
        self.events = EventBroker()
        self.client: TelegramClient | None = None
        self.route: ProxyRoute | None = None
        self.handlers: list[tuple[Any, Any]] = []
        self.login_phone: str | None = None
        self.login_code_hash: str | None = None
        self._lifecycle_lock = asyncio.Lock()
        self._outbox_read_max: dict[int, int] = {}
        self._recent_media: dict[tuple[str, str], Any] = {}
        self._connection_monitor: asyncio.Task | None = None
        self._session_metadata: dict = {}
        self._init_runtime_state()
        info = self.sessions.info()
        self.status = ClientStatus(
            configured=settings.telegram_configured,
            state="CONNECTING" if settings.telegram_configured else "UNCONFIGURED",
            source_session_available=info.source_available,
            client_session_exists=info.client_exists,
        )

    def _init_runtime_state(self) -> None:
        # Telethon entities seen in dialogs and messages. Avatars, chat info
        # and names resolve from here without a network request.
        self._entities: dict[int, Any] = {}
        # Raw Telethon messages, so media downloads skip a get_messages call.
        self._message_cache: OrderedDict[tuple[int, int], Any] = OrderedDict()
        self._inflight: dict[str, asyncio.Future] = {}
        self._dialogs_snapshot: list[Dialog] = []
        self._dialogs_at = 0.0
        self._dialogs_task: asyncio.Task | None = None
        self._photo_ids: dict[int, int] = {}
        self._no_photo: dict[int, float] = {}
        self._background: set[asyncio.Task] = set()

    def _spawn(self, coroutine) -> None:
        # Keep a reference so fire-and-forget tasks are not garbage collected.
        task = asyncio.create_task(coroutine)
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    def _remember_entity(self, entity: Any) -> None:
        if entity is None or isinstance(entity, (int, str)):
            return
        with suppress(Exception):
            self._entities[int(utils.get_peer_id(entity))] = entity

    def _remember_message(self, chat_id: int, message: Any) -> None:
        key = (chat_id, int(message.id))
        cache = self._message_cache
        cache[key] = message
        cache.move_to_end(key)
        while len(cache) > MESSAGE_CACHE_LIMIT:
            cache.popitem(last=False)

    async def _single_flight(self, key: str, factory):
        """Run one coroutine per key; concurrent callers share its result."""
        running = self._inflight.get(key)
        if running is not None:
            return await asyncio.shield(running)
        future = asyncio.ensure_future(factory())
        self._inflight[key] = future
        try:
            return await asyncio.shield(future)
        finally:
            if future.done():
                self._inflight.pop(key, None)
            else:
                future.add_done_callback(lambda _: self._inflight.pop(key, None))

    async def start(self) -> None:
        try:
            await self._start()
        finally:
            # The UI may have connected while we were still connecting.
            await self.events.publish({"type": "READY", "data": self.status.model_dump(mode="json")})

    async def _start(self) -> None:
        if self._connection_monitor is None:
            self._connection_monitor = asyncio.create_task(self._monitor_connection())
        self.sessions.ensure_client_path()
        info = self.sessions.info()
        self.status = self.status.model_copy(
            update={
                "configured": self.settings.telegram_configured,
                "source_session_available": info.source_available,
                "client_session_exists": info.client_exists,
            }
        )
        if not self.settings.telegram_configured:
            self.status = self.status.model_copy(update={"state": "UNCONFIGURED"})
            return
        if info.source_available and not info.client_exists:
            if not self.settings.telegram_auto_import_source:
                self.status = self.status.model_copy(
                    update={"state": "IMPORT_READY", "last_error": None}
                )
                return
            try:
                await self.import_source()
            except DesktopError:
                self.status = self.status.model_copy(
                    update={
                        "state": "IMPORT_READY",
                        "last_error": "Automatic source session import failed",
                    }
                )
            return
        async with self._lifecycle_lock:
            await self._connect()

    async def _monitor_connection(self) -> None:
        while True:
            await asyncio.sleep(5)
            try:
                await self._recover_connection_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("Telegram connection monitor failed", exc_info=True)

    async def _recover_connection_once(self) -> bool:
        client = self.client
        if client is None or not self.status.authorized or client.is_connected():
            return False
        async with self._lifecycle_lock:
            client = self.client
            if client is None or not self.status.authorized or client.is_connected():
                return False
            self._unregister_handlers()
            with suppress(Exception):
                await client.disconnect()
            self.client = None
            if self.route is not None:
                await self.route.deactivate()
            self.route = None
            self.status = self.status.model_copy(
                update={"connected": False, "state": "CONNECTING", "last_error": None}
            )
            await self.events.publish(
                {"type": "READY", "data": self.status.model_dump(mode="json")}
            )
            await self._connect()
            await self.events.publish(
                {"type": "READY", "data": self.status.model_dump(mode="json")}
            )
            return self.status.connected

    async def _connect(self, avoid: str | None = None) -> None:
        routes = self.transport.load()
        selected = self.transport.selected_index()

        # Always keep a fallback chain. A stale saved selection (for example
        # direct=0 from an older install) must not prevent healthy proxies from
        # being tried.
        candidates: list[ProxyRoute | None] = []
        if selected == 0:
            candidates.append(None)
            candidates.extend(routes)
        elif selected is not None and 1 <= selected <= len(routes):
            preferred = routes[selected - 1]
            candidates.append(preferred)
            candidates.extend(route for index, route in enumerate(routes, 1) if index != selected)
            if self.settings.telegram_allow_direct:
                candidates.append(None)
        else:
            candidates.extend(routes)
            if self.settings.telegram_allow_direct:
                candidates.append(None)
        if not candidates:
            self.status = self.status.model_copy(
                update={"state": "PROXY_ERROR", "last_error": "No Telegram route is configured"}
            )
            return
        if avoid is not None:
            # The route that just dropped a request goes to the back of the
            # line; the others get a chance first.
            def name(route: ProxyRoute | None) -> str:
                return route.display_name if route is not None else "direct"

            candidates = [item for item in candidates if name(item) != avoid] + [
                item for item in candidates if name(item) == avoid
            ]

        runtime_session, session_metadata = self.sessions.open_runtime_session()
        self._session_metadata = session_metadata
        self.status = self.status.model_copy(
            update={
                "session_dc_id": session_metadata.get("dc_id"),
                "session_auth_key_present": bool(session_metadata.get("auth_key_present")),
                "session_auth_key_bytes": int(session_metadata.get("auth_key_bytes") or 0),
                "runtime_session_cloned": runtime_session is not None and not session_metadata.get("persistent"),
            }
        )

        route_errors: list[str] = []
        for route in candidates:
            client: TelegramClient | None = None
            try:
                self.status = self.status.model_copy(
                    update={"state": "CONNECTING", "last_error": None}
                )
                route_options = await route.activate() if route is not None else None
                client = build_client(
                    self.settings,
                    route_options,
                    session=runtime_session,
                )
                await client.connect()
                authorized = await client.is_user_authorized()
                self.client = client
                self.route = route
                if authorized:
                    await self._mark_authorized()
                else:
                    self._clear_update_state(runtime_session)
                    self.status = self.status.model_copy(
                        update={
                            "connected": True,
                            "authorized": False,
                            "state": "AUTH_REQUIRED",
                            "active_route": route.display_name if route else "direct",
                        }
                    )
                return
            except (Exception, asyncio.CancelledError) as error:
                task = asyncio.current_task()
                if isinstance(error, asyncio.CancelledError) and task is not None and task.cancelling():
                    raise
                # A proxy that drops the connection mid-handshake cancels
                # Telethon's pending request; treat it as a failed route.
                route_name = route.display_name if route is not None else "direct"
                message = str(error).strip().replace("\n", " ")
                short = f"{type(error).__name__}: {message}" if message else type(error).__name__
                route_errors.append(f"{route_name}: {short[:180]}")
                logger.warning("Telegram route failed (%s): %s", route_name, short)
                if client is not None:
                    try:
                        await client.disconnect()
                    except Exception:
                        pass
                if route is not None:
                    await route.deactivate()

        detail = " · ".join(route_errors[:3])
        self.status = self.status.model_copy(
            update={
                "connected": False,
                "authorized": False,
                "state": "PROXY_ERROR",
                "last_error": "All Telegram routes failed" + (f" ({detail})" if detail else ""),
            }
        )

    @staticmethod
    def _clear_update_state(session: Any) -> None:
        """Drop pts/qts saved by an earlier login; they are wrong for a new one."""
        if not isinstance(session, SQLiteSession):
            return
        try:
            session._execute("delete from update_state")
            session.save()
        except Exception:
            logger.warning("Stale update state could not be cleared", exc_info=True)

    async def _catch_up_missed(self, client: TelegramClient) -> None:
        """Fetch what arrived while the app was closed, from the saved pts/qts."""
        try:
            from telethon._updates import ChannelState, SessionState

            box = client._message_box
            if box.is_empty():
                account = SessionState(0, 0, False, 0, 0, 0, 0, None)
                channels = []
                for entity_id, state in await utils.maybe_async(client.session.get_update_states()):
                    if entity_id == 0:
                        account = SessionState(
                            0, 0, False, state.pts, state.qts, int(state.date.timestamp()), state.seq, None
                        )
                    else:
                        channels.append(ChannelState(entity_id, state.pts))
                box.load(account, channels)
            await client.catch_up()
        except Exception:
            logger.warning("Catching up on missed updates failed", exc_info=True)

    async def set_runtime_config(self, values: ApiConfigRequest) -> ClientStatus:
        key = values.api_hash.strip()
        if values.api_id < 1 or len(key) < 16:
            raise DesktopError("API ID یا API Hash معتبر نیست.")

        target = self.settings.data_root / "settings.env"
        target.parent.mkdir(parents=True, exist_ok=True)
        direct_allowed = self.settings.telegram_allow_direct or not self.transport.load()
        target.write_text(
            f"TELEGRAM_API_ID={values.api_id}\n"
            f"TELEGRAM_API_HASH={key}\n"
            f"TELEGRAM_ALLOW_DIRECT={'true' if direct_allowed else 'false'}\n",
            encoding="utf-8",
        )

        async with self._lifecycle_lock:
            self.settings.telegram_api_id = values.api_id
            self.settings.telegram_api_hash = SecretStr(key)
            self.settings.telegram_allow_direct = direct_allowed
            self._unregister_handlers()
            if self.client is not None:
                with suppress(Exception):
                    await self.client.disconnect()
            self.client = None
            if self.route is not None:
                with suppress(Exception):
                    await self.route.deactivate()
            self.route = None

            info = self.sessions.info()
            self.status = self.status.model_copy(
                update={
                    "configured": True,
                    "connected": False,
                    "authorized": False,
                    "state": "CONNECTING",
                    "client_session_exists": info.client_exists,
                    "last_error": None,
                }
            )
            await self._connect()
            self.transfer_bundle.sync(include_session=self.status.authorized)
            await self.events.publish(
                {"type": "READY", "data": self.status.model_dump(mode="json")}
            )
            return self.status

    async def import_source(self) -> ClientStatus:
        if not self.settings.telegram_configured:
            raise DesktopError("Telegram API credentials are not configured")
        async with self._lifecycle_lock:
            if self.client is not None and self.status.connected:
                raise DesktopError("Disconnect the current Telegram connection before importing")
            try:
                await asyncio.to_thread(SessionImporter(self.sessions).import_source)
            except ValueError as exc:
                raise DesktopError(str(exc)) from None

            info = self.sessions.info()
            self.status = self.status.model_copy(
                update={
                    "client_session_exists": info.client_exists,
                    "source_session_available": info.source_available,
                    "state": "CONNECTING",
                    "last_error": None,
                }
            )
            await self._connect()
            return self.status

    @staticmethod
    def _auth_error(error: Exception, fallback: str) -> DesktopError:
        if isinstance(error, PhoneNumberInvalidError):
            return DesktopError("شماره تلفن نامعتبر است.")
        if isinstance(error, PhoneCodeInvalidError):
            return DesktopError("کد تأیید نادرست است.")
        if isinstance(error, PhoneCodeExpiredError):
            return DesktopError("کد تأیید منقضی شده است؛ دوباره کد بگیرید.")
        if isinstance(error, PasswordHashInvalidError):
            return DesktopError("رمز دومرحله‌ای نادرست است.")
        if isinstance(error, FloodWaitError):
            seconds = max(int(getattr(error, "seconds", 0) or 0), 1)
            return DesktopError(f"تلاش‌های ورود محدود شده؛ {seconds} ثانیه بعد دوباره امتحان کنید.")
        return DesktopError(fallback)

    @staticmethod
    def _log_auth_error(error: Exception) -> None:
        logger.warning("Telegram authentication operation failed: %s", type(error).__name__)

    def _clear_login_challenge(self) -> None:
        self.login_phone = None
        self.login_code_hash = None

    async def _mark_authorized(self) -> None:
        if self.client is None:
            raise DesktopError("Telegram client is not connected")
        account = await self.client.get_me()
        self._remember_entity(account)
        self._register_handlers()
        self._spawn(self._catch_up_missed(self.client))
        self.status = self.status.model_copy(
            update={
                "connected": True,
                "authorized": True,
                "state": "CONNECTED",
                "user_id": account.id,
                "display_name": " ".join(filter(None, [account.first_name, account.last_name])),
                "phone": getattr(account, "phone", None),
                "active_route": self.route.display_name if self.route else "direct",
                "last_error": None,
                "client_session_exists": True,
            }
        )
        try:
            sync_account_to_portable(
                self.settings,
                user_id=int(account.id),
                display_name=self.status.display_name,
                phone=self.status.phone,
            )
        except Exception:
            logger.warning("Portable account bundle could not be updated", exc_info=True)
        self.transfer_bundle.sync(include_session=True)
        # Warm the dialog list so the UI's first live request is answered fast.
        self._spawn(self._warm_dialogs())

    async def _warm_dialogs(self) -> None:
        try:
            await self._fetch_dialogs()
        except Exception:
            logger.warning("Initial dialog refresh failed", exc_info=True)

    def _register_handlers(self) -> None:
        if self.client is None or self.handlers:
            return
        definitions = [
            (self._on_new, events.NewMessage()),
            (self._on_edit, events.MessageEdited()),
            (self._on_delete, events.MessageDeleted()),
            (self._on_reaction, events.Raw(types=types.UpdateMessageReactions)),
            (self._on_user_update, events.UserUpdate()),
            (self._on_read, events.MessageRead()),
        ]
        for callback, builder in definitions:
            self.client.add_event_handler(callback, builder)
            self.handlers.append((callback, builder))

    def _unregister_handlers(self) -> None:
        if self.client is not None:
            for callback, builder in self.handlers:
                self.client.remove_event_handler(callback, builder)
        self.handlers.clear()

    def _persist_message_background(self, message: Message) -> None:
        async def persist() -> None:
            try:
                await self.store.upsert_message(message)
            except Exception:
                logger.warning(
                    "Live message persistence failed for chat=%s message=%s",
                    message.chat_id,
                    message.message_id,
                    exc_info=True,
                )

        self._spawn(persist())

    @staticmethod
    def _as_utc(value: datetime | None) -> datetime:
        if value is None:
            return datetime.now(timezone.utc)
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

    @staticmethod
    def _sender_name(message: Any) -> str | None:
        post_author = getattr(message, "post_author", None)
        if post_author:
            return str(post_author)
        sender = getattr(message, "sender", None)
        if sender is None:
            return None
        title = getattr(sender, "title", None)
        name = " ".join(filter(None, [getattr(sender, "first_name", None), getattr(sender, "last_name", None)]))
        return name or title or getattr(sender, "username", None)

    @staticmethod
    def _media(message: Any) -> MediaInfo | None:
        return convert.media_info(message)

    @staticmethod
    def _reactions(message: Any) -> list[ReactionSummary]:
        return TelegramDesktopService._reaction_summary(getattr(message, "reactions", None))

    @staticmethod
    def _reaction_summary(summary: Any) -> list[ReactionSummary]:
        values = []
        for item in getattr(summary, "results", None) or []:
            reaction = getattr(item, "reaction", None)
            emoji = getattr(reaction, "emoticon", None)
            if not emoji:
                continue
            count = int(getattr(item, "count", 0) or 0)
            if count < 1:
                continue
            values.append(
                ReactionSummary(
                    emoji=str(emoji),
                    count=count,
                    chosen=getattr(item, "chosen_order", None) is not None,
                )
            )
        return values

    def _message_model(self, message: Any, chat_id: int, edited: bool = False) -> Message:
        message_id = int(message.id)
        outgoing = bool(getattr(message, "out", False))
        read_max = getattr(self, "_outbox_read_max", {}).get(chat_id, 0)
        if hasattr(self, "_entities"):
            self._remember_entity(getattr(message, "sender", None))
            self._remember_message(chat_id, message)
        sender_name = self._sender_name(message)
        edit_date = getattr(message, "edit_date", None)
        grouped_id = getattr(message, "grouped_id", None)
        views = getattr(message, "views", None)
        via_bot = getattr(message, "via_bot", None) if getattr(message, "via_bot_id", None) else None
        return Message(
            chat_id=chat_id,
            message_id=message_id,
            text=str(getattr(message, "raw_text", None) or ""),
            date=self._as_utc(getattr(message, "date", None)),
            sender_id=getattr(message, "sender_id", None),
            sender_name=sender_name,
            outgoing=outgoing,
            edited=edited or (edit_date is not None and not getattr(message, "edit_hide", False)),
            reply_to_message_id=getattr(message, "reply_to_msg_id", None),
            media=self._media(message),
            reactions=self._reactions(message),
            read=outgoing and message_id <= read_max,
            entities=convert.entities(message),
            forward_from=convert.forward_name(message),
            grouped_id=int(grouped_id) if isinstance(grouped_id, int) else None,
            views=int(views) if isinstance(views, int) else None,
            post=bool(getattr(message, "post", False)),
            action=convert.action_text(message, sender_name),
            link_preview=convert.link_preview(message),
            via_bot=getattr(via_bot, "username", None),
        )

    @staticmethod
    def _entity_dialog_type(entity: Any) -> str:
        if hasattr(entity, "first_name"):
            return "user"
        if bool(getattr(entity, "megagroup", False)):
            return "supergroup"
        if bool(getattr(entity, "broadcast", False)):
            return "channel"
        if hasattr(entity, "title"):
            return "group"
        return "unknown"

    @staticmethod
    def _entity_title(entity: Any, chat_id: int) -> str:
        return convert.display_name(entity) or str(chat_id)

    @staticmethod
    def _status_label(status: Any) -> str | None:
        if status is None:
            return None
        labels = {
            "UserStatusOnline": "online",
            "UserStatusOffline": "offline",
            "UserStatusRecently": "recently",
            "UserStatusLastWeek": "last_week",
            "UserStatusLastMonth": "last_month",
        }
        return labels.get(type(status).__name__)

    @staticmethod
    def _entity_status(entity: Any) -> str | None:
        return TelegramDesktopService._status_label(getattr(entity, "status", None))

    @staticmethod
    def _dialog_muted(dialog: Any) -> bool:
        raw_dialog = getattr(dialog, "dialog", None)
        settings = getattr(raw_dialog, "notify_settings", None)
        mute_until = getattr(settings, "mute_until", None)
        if mute_until is None:
            return False
        if isinstance(mute_until, datetime):
            return TelegramDesktopService._as_utc(mute_until) > datetime.now(timezone.utc)
        try:
            return int(mute_until) > int(datetime.now(timezone.utc).timestamp())
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _dialog_model(dialog: Any) -> Dialog:
        entity = dialog.entity
        latest = getattr(dialog, "message", None)
        raw_dialog = getattr(dialog, "dialog", None)
        if dialog.is_user:
            kind = "user"
        elif dialog.is_channel:
            kind = "supergroup" if getattr(entity, "megagroup", False) else "channel"
        elif dialog.is_group:
            kind = "group"
        else:
            kind = "unknown"
        latest_out = bool(getattr(latest, "out", False))
        read_outbox = int(getattr(raw_dialog, "read_outbox_max_id", 0) or 0)
        sender = None
        if latest is not None and kind in {"group", "supergroup"} and not isinstance(latest, types.MessageService):
            sender = "شما" if latest_out else convert.first_name(getattr(latest, "sender", None))
        return Dialog(
            chat_id=int(dialog.id),
            title=str(dialog.title or ""),
            dialog_type=kind,
            username=getattr(entity, "username", None),
            unread_count=int(getattr(dialog, "unread_count", 0) or 0),
            pinned=bool(getattr(dialog, "pinned", False)),
            archived=bool(getattr(dialog, "folder_id", None) == 1),
            muted=TelegramDesktopService._dialog_muted(dialog),
            last_message_id=getattr(latest, "id", None),
            last_message_at=getattr(latest, "date", None),
            last_message_preview=convert.preview_text(latest),
            last_message_sender=sender,
            last_message_outgoing=latest_out,
            last_message_read=latest_out and int(getattr(latest, "id", 0) or 0) <= read_outbox,
        )

    async def _on_new(self, event: Any) -> None:
        if event.chat_id is None:
            return
        chat_id = int(event.chat_id)
        message = self._message_model(event.message, chat_id)
        self._dialogs_at = 0.0  # previews changed; next list request refetches
        # Publish before persisting: the UI must never wait on the disk.
        await self.events.publish({"type": "MESSAGE_NEW", "data": message.model_dump(mode="json")})
        self._persist_message_background(message)

    async def _on_edit(self, event: Any) -> None:
        if event.chat_id is None:
            return
        chat_id = int(event.chat_id)
        message = self._message_model(event.message, chat_id, edited=True)
        await self.events.publish({"type": "MESSAGE_EDITED", "data": message.model_dump(mode="json")})
        self._persist_message_background(message)

    async def _on_user_update(self, event: Any) -> None:
        if event.action is None:
            status = getattr(event, "status", None)
            if status is not None and event.user_id is not None:
                user_id = int(event.user_id)
                entity = self._entities.get(user_id)
                if entity is not None:
                    with suppress(Exception):
                        entity.status = status
                await self.events.publish(
                    {
                        "type": "USER_STATUS",
                        "data": {"user_id": user_id, "status": self._status_label(status)},
                    }
                )
            return
        if event.chat_id is None:
            return
        if event.user_id == self.status.user_id:
            return

        if event.cancel:
            action = "cancel"
            active = False
        elif event.typing:
            action = "typing"
            active = True
        elif event.uploading:
            action = "uploading"
            active = True
        elif event.recording:
            action = "recording"
            active = True
        else:
            return

        user_name = None
        cached = self._entities.get(int(event.user_id or 0))
        if cached is not None:
            user_name = convert.first_name(cached)
        else:
            try:
                user = await event.get_user()
                if user is not None:
                    self._remember_entity(user)
                    user_name = convert.first_name(user)
            except Exception:
                pass

        await self.events.publish(
            {
                "type": "CHAT_ACTION",
                "data": {
                    "chat_id": int(event.chat_id),
                    "user_id": event.user_id,
                    "user_name": user_name,
                    "action": action,
                    "active": active,
                },
            }
        )

    async def _on_read(self, event: Any) -> None:
        if event.chat_id is None or not event.outbox:
            return
        max_id = int(event.max_id or 0)
        if max_id < 1:
            return
        chat_id = int(event.chat_id)
        current = getattr(self, "_outbox_read_max", {}).get(chat_id, 0)
        if max_id <= current:
            return
        self._outbox_read_max[chat_id] = max_id
        await self.store.mark_outgoing_read(chat_id, max_id)
        await self.events.publish(
            {
                "type": "MESSAGES_READ",
                "data": {"chat_id": chat_id, "max_id": max_id},
            }
        )

    async def _on_delete(self, event: Any) -> None:
        deleted_ids = [int(value) for value in event.deleted_ids]
        targets: dict[int | None, list[int]]
        if event.chat_id is not None:
            targets = {int(event.chat_id): deleted_ids}
        else:
            # Private chats and basic groups: Telegram sends only the ids,
            # which are unique per account, so find their chat locally.
            targets = dict(await self.store.chats_for_shared_ids(deleted_ids))
            known = {value for values in targets.values() for value in values}
            unknown = [value for value in deleted_ids if value not in known]
            if unknown:
                # The UI drops these from whichever non-channel chat is open.
                targets[None] = unknown
        for chat_id, message_ids in targets.items():
            for message_id in message_ids:
                if chat_id is not None:
                    await self.store.mark_deleted(chat_id, message_id)
                    self._message_cache.pop((chat_id, message_id), None)
                await self.events.publish(
                    {
                        "type": "MESSAGE_DELETED",
                        "data": {"chat_id": chat_id, "message_id": message_id},
                    }
                )

    async def _on_reaction(self, update: Any) -> None:
        try:
            chat_id = int(utils.get_peer_id(update.peer))
            message_id = int(update.msg_id)
            reactions = self._reaction_summary(update.reactions)
            partial = bool(getattr(update.reactions, "min", False))
            await self.events.publish(
                {
                    "type": "MESSAGE_REACTIONS",
                    "data": {
                        "chat_id": chat_id,
                        "message_id": message_id,
                        "reactions": [item.model_dump(mode="json") for item in reactions],
                        # "min" updates do not say which reaction is ours.
                        "min": partial,
                    },
                }
            )
            if not partial:
                await self.store.update_reactions(chat_id, message_id, reactions)
        except Exception as error:
            logger.warning(
                "Telegram reaction update could not be synchronized: %s",
                type(error).__name__,
            )

    def _require_authorized(self) -> TelegramClient:
        if self.client is None or not self.status.connected or not self.status.authorized:
            raise DesktopError("Telegram is not connected and authorized")
        return self.client

    async def add_proxy_link(self, link: str) -> dict:
        try:
            result = self.transport.add_proxy_link(link)
            self.transfer_bundle.sync(include_session=self.status.authorized)
            return result
        except ValueError:
            raise

    async def select_proxy(self, index: int | None) -> dict:
        routes = self.transport.load()
        if index is not None and index != 0 and not (1 <= index <= len(routes)):
            raise ValueError("Proxy selection is invalid")
        async with self._lifecycle_lock:
            self.transport.set_selected_index(index)
            client = self.client
            self._unregister_handlers()
            if client is not None:
                with suppress(Exception):
                    await client.disconnect()
            self.client = None
            if self.route is not None:
                with suppress(Exception):
                    await self.route.deactivate()
            self.route = None
            await self._connect()
            self.transfer_bundle.sync(include_session=self.status.authorized)
            await self.events.publish({"type": "READY", "data": self.status.model_dump(mode="json")})
        return {
            "selected_index": index,
            "active_route": self.status.active_route,
            "connected": self.status.connected,
        }

    async def probe_proxies(self) -> list[dict]:
        routes = self.transport.load()

        async def probe_one(index: int, route: ProxyRoute) -> dict:
            started = asyncio.get_running_loop().time()
            client: TelegramClient | None = None
            try:
                options = await route.activate()
                api_hash = (
                    self.settings.telegram_api_hash.get_secret_value()
                    if self.settings.telegram_api_hash
                    else "probe-only-placeholder"
                )
                client = TelegramClient(
                    MemorySession(),
                    self.settings.telegram_api_id or 1,
                    api_hash,
                    connection_retries=1,
                    request_retries=1,
                    auto_reconnect=False,
                    sequential_updates=True,
                    receive_updates=False,
                    **options,
                )
                await asyncio.wait_for(client.connect(), timeout=4.5)
                latency = round((asyncio.get_running_loop().time() - started) * 1000, 2)
                return {
                    "index": index,
                    "available": True,
                    "latency_ms": latency,
                    "detail": "Telegram MTProto handshake OK",
                }
            except Exception as error:
                return {
                    "index": index,
                    "available": False,
                    "latency_ms": None,
                    "detail": f"Telegram handshake failed: {type(error).__name__}",
                }
            finally:
                if client is not None:
                    with suppress(Exception):
                        await client.disconnect()
                with suppress(Exception):
                    await route.deactivate()

        return await asyncio.gather(
            *(probe_one(index, route) for index, route in enumerate(routes, 1))
        )

    async def devices(self) -> list[DeviceSession]:
        client = self._require_authorized()
        result = await client(functions.account.GetAuthorizationsRequest())
        return [
            DeviceSession(
                hash=int(item.hash),
                current=bool(item.current),
                device_model=str(item.device_model or "Windows PC"),
                platform=str(item.platform or "Windows"),
                system_version=str(item.system_version or ""),
                app_name=str(item.app_name or "Telegram Desktop"),
                app_version=str(item.app_version or ""),
                date_active=item.date_active,
                country=getattr(item, "country", None),
                region=getattr(item, "region", None),
            )
            for item in result.authorizations
        ]

    async def _entity(self, client: TelegramClient, chat_id: int) -> Any:
        cached = getattr(self, "_entities", {}).get(chat_id)
        if cached is not None:
            return cached
        entity = await client.get_entity(chat_id)
        if hasattr(self, "_entities"):
            self._remember_entity(entity)
        return entity

    async def chat_info(self, chat_id: int) -> ChatInfo:
        client = self._require_authorized()
        entity = await self._entity(client, chat_id)
        return ChatInfo(
            chat_id=chat_id,
            title=self._entity_title(entity, chat_id),
            dialog_type=self._entity_dialog_type(entity),
            username=getattr(entity, "username", None),
            participants_count=getattr(entity, "participants_count", None),
            status=self._entity_status(entity),
            is_bot=bool(getattr(entity, "bot", False)),
            verified=bool(getattr(entity, "verified", False)),
            scam=bool(getattr(entity, "scam", False)),
            fake=bool(getattr(entity, "fake", False)),
            photo_available=bool(getattr(entity, "photo", None)),
        )

    async def download_chat_photo(self, chat_id: int) -> DownloadedMedia:
        client = self._require_authorized()
        root = self.settings.data_root / "avatars"
        target = chat_photo_path(root, chat_id)
        photo_ids = getattr(self, "_photo_ids", {})
        no_photo = getattr(self, "_no_photo", {})
        known = getattr(self, "_entities", {}).get(chat_id)

        def cached() -> DownloadedMedia:
            return DownloadedMedia(path=target, filename=target.name, mime_type="image/jpeg")

        # Answer from disk whenever possible: an avatar only changes when its
        # photo id changes, which the cached entity tells us for free.
        if known is not None:
            photo = getattr(known, "photo", None)
            photo_id = getattr(photo, "photo_id", None)
            if not photo or isinstance(photo, (types.UserProfilePhotoEmpty, types.ChatPhotoEmpty)):
                raise MediaUnavailable("Chat photo is not available")
            if photo_id is not None and photo_ids.get(chat_id) == photo_id and target.is_file():
                return cached()
        elif is_fresh_chat_photo(target, max_age_seconds=AVATAR_MAX_AGE_SECONDS):
            return cached()
        if time.monotonic() < no_photo.get(chat_id, 0):
            raise MediaUnavailable("Chat photo is not available")

        async def fetch() -> DownloadedMedia:
            entity = known if known is not None else await self._entity(client, chat_id)
            photo = getattr(entity, "photo", None)
            if not photo or isinstance(photo, (types.UserProfilePhotoEmpty, types.ChatPhotoEmpty)):
                no_photo[chat_id] = time.monotonic() + NO_PHOTO_RETRY_SECONDS
                raise MediaUnavailable("Chat photo is not available")
            photo_id = getattr(photo, "photo_id", None)
            if photo_id is not None and photo_ids.get(chat_id) == photo_id and target.is_file():
                return cached()
            if photo_id is None and is_fresh_chat_photo(target, max_age_seconds=AVATAR_MAX_AGE_SECONDS):
                return cached()
            root.mkdir(parents=True, exist_ok=True)
            partial = target.with_name(target.name + ".part")
            downloaded = await client.download_profile_photo(entity, file=str(partial))
            if downloaded is None or not partial.is_file() or partial.stat().st_size == 0:
                partial.unlink(missing_ok=True)
                no_photo[chat_id] = time.monotonic() + NO_PHOTO_RETRY_SECONDS
                raise MediaUnavailable("Chat photo download failed")
            partial.replace(target)
            if photo_id is not None:
                photo_ids[chat_id] = photo_id
            return cached()

        if not hasattr(self, "_inflight"):
            return await fetch()
        return await self._single_flight(f"avatar:{chat_id}", fetch)

    async def _get_message(self, client: TelegramClient, chat_id: int, message_id: int, *, fresh: bool = False) -> Any:
        cache = getattr(self, "_message_cache", None)
        if not fresh and cache is not None:
            value = cache.get((chat_id, message_id))
            if value is not None:
                return value
        value = await client.get_messages(chat_id, ids=message_id)
        if value is not None and cache is not None:
            self._remember_message(chat_id, value)
        return value

    @staticmethod
    def _cached_original(root: Path, chat_id: int, message_id: int) -> Path | None:
        for candidate in root.glob(f"{chat_id}_{message_id}_*"):
            if candidate.suffix != ".part" and candidate.is_file() and candidate.stat().st_size > 0:
                return candidate
        return None

    @staticmethod
    def _preview_size(photo: Any) -> Any:
        sizes = [
            size for size in getattr(photo, "sizes", None) or []
            if isinstance(size, (types.PhotoSize, types.PhotoSizeProgressive))
        ]
        if not sizes:
            return None
        sizes.sort(key=lambda size: max(size.w, size.h))
        for size in sizes:
            if max(size.w, size.h) >= CHAT_PHOTO_PREVIEW_SIDE:
                return size
        return sizes[-1]

    async def download_media(self, chat_id: int, message_id: int, *, thumb: bool = False) -> DownloadedMedia:
        client = self._require_authorized()
        root = self.settings.data_root / "downloads"

        if thumb:
            target = root / f"{chat_id}_{message_id}.thumb.jpg"
            if target.is_file() and target.stat().st_size > 0:
                return DownloadedMedia(path=target, filename=target.name, mime_type="image/jpeg")
        else:
            existing = self._cached_original(root, chat_id, message_id)
            if existing is not None:
                name = existing.name.split("_", 2)[-1]
                return DownloadedMedia(
                    path=existing,
                    filename=name,
                    mime_type=mimetypes.guess_type(name)[0] or "application/octet-stream",
                )

        async def fetch() -> DownloadedMedia:
            message = await self._get_message(client, chat_id, message_id)
            if message is None or not getattr(message, "media", None):
                raise MediaUnavailable("Media is not available for this message")
            root.mkdir(parents=True, exist_ok=True)

            if thumb:
                target = root / f"{chat_id}_{message_id}.thumb.jpg"
                photo = getattr(message, "photo", None)
                if photo is not None:
                    size = self._preview_size(photo)
                    if size is None:
                        raise MediaUnavailable("Photo preview is not available")
                    options = {"thumb": size}
                elif getattr(getattr(message, "document", None), "thumbs", None):
                    options = {"thumb": -1}
                else:
                    raise MediaUnavailable("This media has no preview")
                filename = target.name
                mime_type = "image/jpeg"
            else:
                file_info = getattr(message, "file", None)
                mime_type = getattr(file_info, "mime_type", None)
                raw_name = getattr(file_info, "name", None)
                if not raw_name:
                    extension = mimetypes.guess_extension(mime_type or "") or ""
                    if getattr(message, "photo", None):
                        extension = ".jpg"
                    raw_name = f"media_{message_id}{extension}"
                filename = safe_media_name(raw_name, fallback=f"media_{message_id}")
                target = media_path(root, chat_id, message_id, filename)
                options = {}

            # Download beside the target and rename at the end, so a broken
            # transfer never leaves a truncated file in the cache.
            partial = target.with_name(target.name + ".part")
            for attempt in range(2):
                try:
                    downloaded = await client.download_media(message, file=str(partial), **options)
                    break
                except FileReferenceExpiredError:
                    if attempt:
                        raise
                    message = await self._get_message(client, chat_id, message_id, fresh=True)
                    if message is None:
                        raise MediaUnavailable("Media is not available for this message") from None
            if downloaded is None or not partial.is_file():
                partial.unlink(missing_ok=True)
                raise MediaUnavailable("Media is no longer available")
            partial.replace(target)
            return DownloadedMedia(
                path=target,
                filename=filename,
                mime_type=mime_type or mimetypes.guess_type(filename)[0],
            )

        if not hasattr(self, "_inflight"):
            return await fetch()
        return await self._single_flight(f"media:{chat_id}:{message_id}:{int(thumb)}", fetch)

    async def _fetch_dialogs(self) -> list[Dialog]:
        """Fetch every dialog from Telegram once; concurrent callers share it."""
        running = self._dialogs_task
        if running is None or running.done():
            running = asyncio.ensure_future(self._load_dialogs_live())
            self._dialogs_task = running
        return await asyncio.shield(running)

    async def _load_dialogs_live(self) -> list[Dialog]:
        client = self._require_authorized()
        dialogs: list[Dialog] = []
        async for item in client.iter_dialogs():
            self._remember_entity(item.entity)
            if getattr(item, "message", None) is not None:
                self._remember_entity(getattr(item.message, "sender", None))
            value = self._dialog_model(item)
            if self.status.user_id is not None and value.chat_id == int(self.status.user_id):
                value = value.model_copy(update={"title": "Saved Messages"})
            raw_dialog = getattr(item, "dialog", None)
            read_max = int(
                getattr(raw_dialog, "read_outbox_max_id", 0)
                or getattr(item, "read_outbox_max_id", 0)
                or 0
            )
            self._outbox_read_max[value.chat_id] = max(
                self._outbox_read_max.get(value.chat_id, 0),
                read_max,
            )
            dialogs.append(value)
        # Telegram already returns pinned chats first, in their pinned order,
        # then the rest by last activity; keep that order.
        self._dialogs_snapshot = dialogs
        self._dialogs_at = time.monotonic()
        try:
            await self.store.replace_dialogs(dialogs)
        except Exception:
            logger.warning("Dialog cache could not be written", exc_info=True)
        return dialogs

    @staticmethod
    def _filter_dialogs(dialogs: list[Dialog], search: str | None) -> list[Dialog]:
        if not search:
            return list(dialogs)
        needle = search.casefold()
        return [
            value for value in dialogs
            if needle in value.title.casefold()
            or (value.username and needle in value.username.casefold())
        ]

    async def list_dialogs(self, search: str | None = None, cached: bool = False) -> list[Dialog]:
        if cached:
            # Local cache: answered from SQLite in milliseconds, even before
            # Telegram is connected, so the chat list appears immediately.
            return await self.store.list_dialogs(search)
        self._require_authorized()
        if self._dialogs_snapshot and time.monotonic() - self._dialogs_at < DIALOG_REUSE_SECONDS:
            return self._filter_dialogs(self._dialogs_snapshot, search)
        return self._filter_dialogs(await self._fetch_dialogs(), search)

    async def list_dialog_folders(self) -> list[DialogFolder]:
        client = self._require_authorized()
        if self._dialogs_snapshot and time.monotonic() - self._dialogs_at < DIALOG_SNAPSHOT_MAX_AGE:
            dialogs = self._dialogs_snapshot
        else:
            dialogs = await self._fetch_dialogs()
        by_id = {item.chat_id: item for item in dialogs}
        try:
            result = await client(functions.messages.GetDialogFiltersRequest())
        except Exception as error:
            logger.warning("Telegram dialog folders could not be loaded: %s", type(error).__name__)
            raise DesktopError("Telegram dialog folders could not be loaded") from None

        folders: list[DialogFolder] = []
        for raw_filter in getattr(result, "filters", None) or []:
            folder_id = int(getattr(raw_filter, "id", 0) or 0)
            if folder_id <= 0:
                continue
            raw_title = getattr(raw_filter, "title", "")
            title = str(getattr(raw_title, "text", None) or raw_title or "").strip()
            if not title:
                continue

            included: set[int] = set()
            excluded: set[int] = set()
            for peer in (getattr(raw_filter, "pinned_peers", None) or []):
                with suppress(Exception):
                    included.add(int(utils.get_peer_id(peer)))
            for peer in (getattr(raw_filter, "include_peers", None) or []):
                with suppress(Exception):
                    included.add(int(utils.get_peer_id(peer)))
            for peer in (getattr(raw_filter, "exclude_peers", None) or []):
                with suppress(Exception):
                    excluded.add(int(utils.get_peer_id(peer)))

            if bool(getattr(raw_filter, "groups", False)):
                included.update(item.chat_id for item in dialogs if item.dialog_type in {"group", "supergroup"})
            if bool(getattr(raw_filter, "broadcasts", False)):
                included.update(item.chat_id for item in dialogs if item.dialog_type == "channel")
            if bool(getattr(raw_filter, "contacts", False)) or bool(getattr(raw_filter, "non_contacts", False)):
                included.update(item.chat_id for item in dialogs if item.dialog_type == "user")

            included.difference_update(excluded)
            values = [by_id[chat_id] for chat_id in included if chat_id in by_id]
            if bool(getattr(raw_filter, "exclude_archived", False)):
                values = [item for item in values if not item.archived]
            if bool(getattr(raw_filter, "exclude_muted", False)):
                values = [item for item in values if not item.muted]
            if bool(getattr(raw_filter, "exclude_read", False)):
                values = [item for item in values if item.unread_count > 0]

            member_ids = {value.chat_id for value in values}
            ordered_ids = [item.chat_id for item in dialogs if item.chat_id in member_ids]
            folders.append(
                DialogFolder(
                    id=folder_id,
                    title=title,
                    chat_ids=ordered_ids,
                    unread_count=sum(1 for item in values if item.unread_count > 0),
                )
            )
        return folders

    async def _publish_dialog_update(self, chat_id: int, **changes: bool) -> dict:
        value = {"chat_id": chat_id, **changes}
        self._dialogs_at = 0.0
        await self.events.publish({"type": "DIALOG_UPDATED", "data": value})
        return value

    async def set_dialog_pinned(self, chat_id: int, pinned: bool) -> dict:
        client = self._require_authorized()
        try:
            peer = await client.get_input_entity(chat_id)
            await client(
                functions.messages.ToggleDialogPinRequest(
                    pinned=pinned,
                    peer=types.InputDialogPeer(peer=peer),
                )
            )
        except Exception as error:
            logger.warning("Telegram dialog pin operation failed: %s", type(error).__name__)
            raise DesktopError("Telegram dialog pin could not be updated") from None
        return await self._publish_dialog_update(chat_id, pinned=pinned)

    async def set_dialog_archived(self, chat_id: int, archived: bool) -> dict:
        client = self._require_authorized()
        try:
            await client.edit_folder(chat_id, 1 if archived else 0)
        except Exception as error:
            logger.warning("Telegram dialog archive operation failed: %s", type(error).__name__)
            raise DesktopError("Telegram dialog archive could not be updated") from None
        return await self._publish_dialog_update(chat_id, archived=archived)

    async def set_dialog_muted(self, chat_id: int, muted: bool) -> dict:
        client = self._require_authorized()
        try:
            peer = await client.get_input_entity(chat_id)
            mute_until = (
                datetime(2038, 1, 18, tzinfo=timezone.utc)
                if muted
                else datetime.now(timezone.utc)
            )
            await client(
                functions.account.UpdateNotifySettingsRequest(
                    peer=types.InputNotifyPeer(peer=peer),
                    settings=types.InputPeerNotifySettings(mute_until=mute_until),
                )
            )
        except Exception as error:
            logger.warning("Telegram dialog mute operation failed: %s", type(error).__name__)
            raise DesktopError("Telegram dialog mute could not be updated") from None
        return await self._publish_dialog_update(chat_id, muted=muted)

    async def pinned_message(self, chat_id: int) -> Message | None:
        client = self._require_authorized()
        values = await client.get_messages(
            chat_id,
            limit=1,
            filter=types.InputMessagesFilterPinned(),
        )
        if not values:
            return None
        message = self._message_model(values[0], chat_id)
        await self.store.upsert_message(message)
        return message

    async def history(
        self,
        chat_id: int,
        limit: int = 50,
        offset_id: int = 0,
        cached: bool = False,
    ) -> list[Message]:
        if limit < 1 or limit > 200:
            raise ValueError("limit must be between 1 and 200")
        if cached:
            values = await self.store.history(chat_id, limit, offset_id)
            return [value for value in values if not value.deleted]
        client = self._require_authorized()
        values = []
        async for item in client.iter_messages(
            chat_id,
            limit=limit,
            offset_id=offset_id or 0,
        ):
            values.append(self._message_model(item, chat_id))
        await self.store.upsert_messages(values)
        return list(reversed(values))

    async def _own_message(self, chat_id: int, message_id: int) -> tuple[TelegramClient, Any]:
        client = self._require_authorized()
        value = await client.get_messages(chat_id, ids=message_id)
        if value is None:
            raise DesktopError("Message was not found")
        if not bool(getattr(value, "out", False)):
            raise DesktopError("Only your own messages can be changed")
        return client, value

    async def search_messages(
        self,
        chat_id: int,
        query: str,
        limit: int = 50,
    ) -> list[Message]:
        value = query.strip()
        if len(value) < 2:
            raise ValueError("search query must contain at least 2 characters")
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")

        client = self._require_authorized()
        messages = []
        async for item in client.iter_messages(chat_id, search=value, limit=limit):
            messages.append(self._message_model(item, chat_id))
        await self.store.upsert_messages(messages)
        return messages

    async def send_typing(self, chat_id: int, active: bool = True) -> dict:
        client = self._require_authorized()
        try:
            peer = await client.get_input_entity(chat_id)
            action = (
                types.SendMessageTypingAction()
                if active
                else types.SendMessageCancelAction()
            )
            await client(
                functions.messages.SetTypingRequest(
                    peer=peer,
                    action=action,
                )
            )
        except Exception as error:
            logger.warning("Telegram typing operation failed: %s", type(error).__name__)
            raise DesktopError("Telegram typing status could not be updated") from None
        return {"chat_id": chat_id, "typing": active}

    async def send_text(
        self,
        chat_id: int,
        text: str,
        reply_to_message_id: int | None = None,
    ) -> Message:
        client = self._require_authorized()
        value = await client.send_message(
            chat_id,
            text,
            reply_to=reply_to_message_id,
        )
        message = self._message_model(value, chat_id)
        await self.store.upsert_message(message)
        await self.events.publish({"type": "MESSAGE_NEW", "data": message.model_dump(mode="json")})
        return message

    async def send_file(
        self,
        chat_id: int,
        path: str,
        caption: str = "",
        reply_to_message_id: int | None = None,
    ) -> Message:
        messages = await self.send_files(
            chat_id,
            [path],
            caption=caption,
            reply_to_message_id=reply_to_message_id,
        )
        return messages[0]

    async def send_files(
        self,
        chat_id: int,
        paths: list[str],
        caption: str = "",
        reply_to_message_id: int | None = None,
    ) -> list[Message]:
        if not 1 <= len(paths) <= 10:
            raise ValueError("Telegram albums require between 1 and 10 files")
        client = self._require_authorized()
        value = await client.send_file(
            chat_id,
            file=paths[0] if len(paths) == 1 else paths,
            caption=caption or None,
            reply_to=reply_to_message_id,
        )
        values = value if isinstance(value, list) else [value]
        if not values:
            raise DesktopError("Telegram did not return the uploaded message")

        messages = [self._message_model(item, chat_id) for item in values]
        for message in messages:
            await self.store.upsert_message(message)
            await self.events.publish(
                {"type": "MESSAGE_NEW", "data": message.model_dump(mode="json")}
            )
        return messages

    @staticmethod
    def _recent_media_label(document: Any, fallback: str) -> str:
        for attribute in getattr(document, "attributes", None) or []:
            alt = getattr(attribute, "alt", None)
            if alt:
                return str(alt)
            file_name = getattr(attribute, "file_name", None)
            if file_name:
                return str(file_name)
        return fallback

    async def recent_media(self) -> dict[str, list[RecentMediaItem]]:
        client = self._require_authorized()
        try:
            stickers_result, gifs_result = await asyncio.gather(
                client(functions.messages.GetRecentStickersRequest(attached=False, hash=0)),
                client(functions.messages.GetSavedGifsRequest(hash=0)),
            )
        except Exception:
            logger.warning("Telegram recent media query failed", exc_info=True)
            raise DesktopError("Recent stickers and GIFs could not be loaded") from None

        result: dict[str, list[RecentMediaItem]] = {"stickers": [], "gifs": []}
        self._recent_media.clear()
        for kind, values, target, fallback in (
            ("sticker", getattr(stickers_result, "stickers", None) or [], "stickers", "استیکر"),
            ("gif", getattr(gifs_result, "gifs", None) or [], "gifs", "GIF"),
        ):
            for document in values[:40]:
                media_id = str(getattr(document, "id", ""))
                if not media_id:
                    continue
                self._recent_media[(kind, media_id)] = document
                result[target].append(
                    RecentMediaItem(
                        media_id=media_id,
                        kind=kind,
                        label=self._recent_media_label(document, fallback),
                        mime_type=getattr(document, "mime_type", None),
                    )
                )
        return result

    async def recent_media_preview(self, kind: str, media_id: str) -> DownloadedMedia:
        """Small preview image of a recent sticker or GIF for the picker grid."""
        client = self._require_authorized()
        document = self._recent_media.get((kind, media_id))
        if document is None:
            raise MediaUnavailable("Recent media is not loaded")
        root = self.settings.data_root / "downloads" / "recent"
        safe_id = safe_media_name(media_id, fallback="media")
        target = root / f"{kind}_{safe_id}.thumb"
        if target.is_file() and target.stat().st_size > 0:
            return DownloadedMedia(path=target, filename=target.name, mime_type=self._sniff_image(target))

        async def fetch() -> DownloadedMedia:
            root.mkdir(parents=True, exist_ok=True)
            partial = target.with_name(target.name + ".part")
            mime = getattr(document, "mime_type", None)
            if kind == "sticker" and mime == "image/webp":
                downloaded = await client.download_media(document, file=str(partial))
            elif getattr(document, "thumbs", None):
                downloaded = await client.download_media(document, file=str(partial), thumb=-1)
            else:
                raise MediaUnavailable("This media has no preview")
            if downloaded is None or not partial.is_file():
                partial.unlink(missing_ok=True)
                raise MediaUnavailable("Preview download failed")
            partial.replace(target)
            return DownloadedMedia(path=target, filename=target.name, mime_type=self._sniff_image(target))

        return await self._single_flight(f"recent:{kind}:{media_id}", fetch)

    @staticmethod
    def _sniff_image(path: Path) -> str:
        with path.open("rb") as handle:
            head = handle.read(12)
        if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
            return "image/webp"
        if head[:8] == b"\x89PNG\r\n\x1a\n":
            return "image/png"
        return "image/jpeg"

    async def send_recent_media(
        self,
        chat_id: int,
        kind: str,
        media_id: str,
        caption: str = "",
        reply_to_message_id: int | None = None,
    ) -> Message:
        if kind not in {"sticker", "gif"}:
            raise ValueError("Unsupported recent media kind")
        document = self._recent_media.get((kind, media_id))
        if document is None:
            await self.recent_media()
            document = self._recent_media.get((kind, media_id))
        if document is None:
            raise DesktopError("The selected recent media is no longer available")

        client = self._require_authorized()
        value = await client.send_file(
            chat_id,
            file=document,
            caption=caption or None,
            reply_to=reply_to_message_id,
        )
        if isinstance(value, list):
            if not value:
                raise DesktopError("Telegram did not return the sent media")
            value = value[0]
        message = self._message_model(value, chat_id)
        await self.store.upsert_message(message)
        await self.events.publish(
            {"type": "MESSAGE_NEW", "data": message.model_dump(mode="json")}
        )
        return message

    async def edit_text(self, chat_id: int, message_id: int, text: str) -> Message:
        client, _ = await self._own_message(chat_id, message_id)
        value = await client.edit_message(chat_id, message_id, text)
        message = self._message_model(value, chat_id, edited=True)
        await self.store.upsert_message(message)
        await self.events.publish({"type": "MESSAGE_EDITED", "data": message.model_dump(mode="json")})
        return message

    async def set_reaction(
        self,
        chat_id: int,
        message_id: int,
        emoji: str | None,
    ) -> Message:
        client = self._require_authorized()
        normalized = (emoji or "").strip()
        if len(normalized) > 16:
            raise ValueError("reaction emoji is too long")

        existing = await client.get_messages(chat_id, ids=message_id)
        if existing is None:
            raise DesktopError("Message was not found")

        try:
            peer = await client.get_input_entity(chat_id)
            reaction = [types.ReactionEmoji(emoticon=normalized)] if normalized else None
            await client(
                functions.messages.SendReactionRequest(
                    peer=peer,
                    msg_id=message_id,
                    reaction=reaction,
                )
            )
        except Exception as error:
            logger.warning("Telegram reaction operation failed: %s", type(error).__name__)
            raise DesktopError("Telegram rejected this reaction for the selected message") from None

        value = await client.get_messages(chat_id, ids=message_id)
        if value is None:
            raise DesktopError("Message was not found after updating its reaction")
        message = self._message_model(value, chat_id)
        await self.store.upsert_message(message)
        await self.events.publish(
            {"type": "MESSAGE_EDITED", "data": message.model_dump(mode="json")}
        )
        return message

    async def delete_message(self, chat_id: int, message_id: int) -> dict:
        client, _ = await self._own_message(chat_id, message_id)
        await client.delete_messages(chat_id, [message_id], revoke=True)
        await self.store.mark_deleted(chat_id, message_id)
        packet = {"chat_id": chat_id, "message_id": message_id}
        await self.events.publish({"type": "MESSAGE_DELETED", "data": packet})
        return {**packet, "deleted": True}

    async def forward_message(
        self,
        source_chat_id: int,
        message_id: int,
        target_chat_id: int,
    ) -> Message:
        client = self._require_authorized()
        source = await client.get_messages(source_chat_id, ids=message_id)
        if source is None:
            raise DesktopError("Message was not found")

        value = await client.forward_messages(target_chat_id, source)
        if isinstance(value, list):
            if not value:
                raise DesktopError("Telegram did not return the forwarded message")
            value = value[0]

        message = self._message_model(value, target_chat_id)
        await self.store.upsert_message(message)
        await self.events.publish({"type": "MESSAGE_NEW", "data": message.model_dump(mode="json")})
        return message

    async def mark_read(self, chat_id: int) -> dict:
        client = self._require_authorized()
        await client.send_read_acknowledge(chat_id)
        await self.store.mark_dialog_read(chat_id)
        return {"chat_id": chat_id, "read": True}

    async def _reconnect_unauthorized(self) -> None:
        """Rebuild the login connection (the monitor only heals logged-in ones)."""
        async with self._lifecycle_lock:
            client = self.client
            if client is not None:
                with suppress(Exception):
                    await client.disconnect()
            self.client = None
            failed = self.route.display_name if self.route is not None else "direct"
            if self.route is not None:
                with suppress(Exception):
                    await self.route.deactivate()
            self.route = None
            await self._connect(avoid=failed if client is not None else None)
            await self.events.publish({"type": "READY", "data": self.status.model_dump(mode="json")})

    async def _ensure_login_connection(self) -> TelegramClient:
        if self.client is None or not self.status.connected or not self.client.is_connected():
            # A proxy can drop an idle login connection without notice.
            await self._reconnect_unauthorized()
        if self.client is None or not self.status.connected:
            raise DesktopError(CONNECTION_UNAVAILABLE)
        return self.client

    async def _login_call(self, call, fallback: str):
        """Run a login request, reconnecting once if the proxy drops it.

        When the connection breaks mid-request Telethon cancels the pending
        request, which surfaces as CancelledError rather than ConnectionError.
        """
        for attempt in range(2):
            client = await self._ensure_login_connection()
            try:
                return await call(client)
            except (ConnectionError, asyncio.CancelledError) as error:
                task = asyncio.current_task()
                if isinstance(error, asyncio.CancelledError) and task is not None and task.cancelling():
                    raise  # the request itself was cancelled, not the connection
                self._log_auth_error(error)
                if attempt:
                    raise DesktopError(CONNECTION_DROPPED) from None
                await self._reconnect_unauthorized()
            except (SessionPasswordNeededError, DesktopError):
                raise
            except Exception as error:
                self._log_auth_error(error)
                raise self._auth_error(error, fallback) from None
        raise DesktopError(CONNECTION_DROPPED)

    async def send_login_code(self, phone: str) -> dict:
        await self._ensure_login_connection()
        if self.status.authorized:
            raise DesktopError("Log out before authorizing another account")
        number = phone.strip()
        sent = await self._login_call(
            lambda client: client.send_code_request(number),
            "ارسال کد تأیید انجام نشد.",
        )
        self.login_phone = number
        self.login_code_hash = sent.phone_code_hash
        self.status = self.status.model_copy(update={"state": "AUTH_REQUIRED", "last_error": None})
        return {"code_sent": True, "requires_2fa": False}

    async def verify_code(self, code: str) -> dict:
        if self.client is None or not self.login_phone or not self.login_code_hash:
            raise DesktopError("Request a new login code")
        phone, code_hash = self.login_phone, self.login_code_hash
        try:
            await self._login_call(
                lambda client: client.sign_in(phone=phone, code=code.strip(), phone_code_hash=code_hash),
                "تأیید کد انجام نشد.",
            )
        except SessionPasswordNeededError:
            return {"code_sent": True, "requires_2fa": True, "authorized": False}
        await self._mark_authorized()
        self._clear_login_challenge()
        return {"code_sent": True, "requires_2fa": False, "authorized": True}

    async def verify_password(self, password: str) -> dict:
        if self.client is None:
            raise DesktopError("Request a new login code")
        await self._login_call(
            lambda client: client.sign_in(password=password),
            "تأیید رمز دومرحله‌ای انجام نشد.",
        )
        await self._mark_authorized()
        self._clear_login_challenge()
        return {"code_sent": True, "requires_2fa": False, "authorized": True}

    async def logout(self) -> None:
        async with self._lifecycle_lock:
            logged_out_user_id = self.status.user_id
            self._unregister_handlers()
            if self.client is not None:
                try:
                    await self.client.log_out()
                except Exception:
                    logger.warning("Telegram logout request failed")
                with suppress(Exception):
                    await self.client.disconnect()
            self.client = None
            if self.route is not None:
                await self.route.deactivate()
            self.route = None
            self.login_phone = None
            self.login_code_hash = None
            self._init_runtime_state()
            self.sessions.remove_client_session()
            self.transfer_bundle.remove_session()
            self.transfer_bundle.sync(include_session=False)
            try:
                remove_account_from_portable(self.settings, logged_out_user_id)
            except Exception:
                logger.warning("Portable account bundle could not remove logged-out account", exc_info=True)
            info = self.sessions.info()
            self.status = ClientStatus(
                configured=self.settings.telegram_configured,
                state="AUTH_REQUIRED" if self.settings.telegram_configured else "UNCONFIGURED",
                source_session_available=info.source_available,
                client_session_exists=info.client_exists,
            )

    async def close(self) -> None:
        if self._connection_monitor is not None:
            self._connection_monitor.cancel()
            with suppress(asyncio.CancelledError):
                await self._connection_monitor
            self._connection_monitor = None
        for task in tuple(self._background):
            task.cancel()
        self._unregister_handlers()
        if self.client is not None:
            await self.client.disconnect()
        self.client = None
        if self.route is not None:
            await self.route.deactivate()
        self.route = None
        self.status = self.status.model_copy(update={"connected": False, "state": "STOPPED"})
