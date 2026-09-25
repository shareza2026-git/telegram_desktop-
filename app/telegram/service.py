import asyncio
from contextlib import suppress
import logging
import mimetypes
from datetime import datetime, timezone
from typing import Any

from telethon import TelegramClient, events, functions, types, utils
from telethon.errors import (
    FloodWaitError,
    PasswordHashInvalidError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    PhoneNumberInvalidError,
    SessionPasswordNeededError,
)

from app.config import Settings
from app.models import (
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
from app.telegram.client import build_client
from app.telegram.media import DownloadedMedia, media_path, safe_media_name
from app.telegram.profile import chat_photo_path, is_fresh_chat_photo
from app.telegram.session import SessionManager
from app.telegram.session_import import SessionImporter
from app.telegram.transport import ProxyRoute, TransportCatalog


logger = logging.getLogger(__name__)


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
                self._subscribers.discard(queue)
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
        self._priority_chat_ids: set[int] = set()
        self._connection_monitor: asyncio.Task | None = None
        info = self.sessions.info()
        self.status = ClientStatus(
            configured=settings.telegram_configured,
            source_session_available=info.source_available,
            client_session_exists=info.client_exists,
        )

    async def start(self) -> None:
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

    async def _connect(self) -> None:
        routes = self.transport.load()
        selected = self.transport.selected_index()
        if selected == 0:
            candidates: list[ProxyRoute | None] = [None]
        elif selected is not None and 1 <= selected <= len(routes):
            candidates = [routes[selected - 1]]
        else:
            candidates = list(routes)
            if self.settings.telegram_allow_direct:
                candidates.append(None)
        if not candidates:
            self.status = self.status.model_copy(
                update={"state": "PROXY_ERROR", "last_error": "No Telegram route is configured"}
            )
            return

        for route in candidates:
            client: TelegramClient | None = None
            try:
                self.status = self.status.model_copy(
                    update={"state": "CONNECTING", "last_error": None}
                )
                route_options = await route.activate() if route is not None else None
                client = build_client(self.settings, route_options)
                await client.connect()
                authorized = await client.is_user_authorized()
                self.client = client
                self.route = route
                if authorized:
                    await self._mark_authorized()
                else:
                    self.status = self.status.model_copy(
                        update={
                            "connected": True,
                            "authorized": False,
                            "state": "AUTH_REQUIRED",
                            "active_route": route.display_name if route else "direct",
                        }
                    )
                return
            except Exception:
                if client is not None:
                    try:
                        await client.disconnect()
                    except Exception:
                        pass
                if route is not None:
                    await route.deactivate()

        self.status = self.status.model_copy(
            update={"connected": False, "authorized": False, "state": "PROXY_ERROR", "last_error": "All Telegram routes failed"}
        )

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
        self._register_handlers()
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

        asyncio.create_task(persist())

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
        if not getattr(message, "media", None):
            return None
        if getattr(message, "photo", None):
            kind = "photo"
        elif getattr(message, "video", None):
            kind = "video"
        elif getattr(message, "audio", None):
            kind = "audio"
        elif getattr(message, "document", None):
            kind = "file"
        else:
            kind = "other"
        file_info = getattr(message, "file", None)
        return MediaInfo(
            kind=kind,
            name=getattr(file_info, "name", None),
            size=getattr(file_info, "size", None),
            mime_type=getattr(file_info, "mime_type", None),
            playable=False,
            downloadable=True,
        )

    @staticmethod
    def _reactions(message: Any) -> list[ReactionSummary]:
        summary = getattr(message, "reactions", None)
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
        return Message(
            chat_id=chat_id,
            message_id=message_id,
            text=str(getattr(message, "raw_text", None) or ""),
            date=self._as_utc(getattr(message, "date", None)),
            sender_id=getattr(message, "sender_id", None),
            sender_name=self._sender_name(message),
            outgoing=outgoing,
            edited=edited,
            reply_to_message_id=getattr(message, "reply_to_msg_id", None),
            media=self._media(message),
            reactions=self._reactions(message),
            read=outgoing and message_id <= read_max,
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
        title = getattr(entity, "title", None)
        if title:
            return str(title)
        name = " ".join(
            filter(
                None,
                [
                    getattr(entity, "first_name", None),
                    getattr(entity, "last_name", None),
                ],
            )
        )
        return name or getattr(entity, "username", None) or str(chat_id)

    @staticmethod
    def _entity_status(entity: Any) -> str | None:
        status = getattr(entity, "status", None)
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
        if dialog.is_user:
            kind = "user"
        elif dialog.is_channel:
            kind = "supergroup" if getattr(entity, "megagroup", False) else "channel"
        elif dialog.is_group:
            kind = "group"
        else:
            kind = "unknown"
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
            last_message_preview=str(getattr(latest, "raw_text", None) or "").strip()[:180] or None,
        )

    def _is_priority_chat(self, chat_id: int) -> bool:
        return chat_id in self._priority_chat_ids

    async def _on_new(self, event: Any) -> None:
        if event.chat_id is None:
            return
        chat_id = int(event.chat_id)
        message = self._message_model(event.message, chat_id)
        packet = {
            "type": "MESSAGE_NEW",
            "data": message.model_dump(mode="json"),
            "priority": self._is_priority_chat(chat_id),
        }
        if self._is_priority_chat(chat_id):
            await self.events.publish(packet)
            self._persist_message_background(message)
            return

        self._persist_message_background(message)
        await self.events.publish(packet)

    async def _on_edit(self, event: Any) -> None:
        if event.chat_id is None:
            return
        chat_id = int(event.chat_id)
        message = self._message_model(event.message, chat_id, edited=True)
        packet = {
            "type": "MESSAGE_EDITED",
            "data": message.model_dump(mode="json"),
            "priority": self._is_priority_chat(chat_id),
        }
        if self._is_priority_chat(chat_id):
            await self.events.publish(packet)
            self._persist_message_background(message)
            return

        self._persist_message_background(message)
        await self.events.publish(packet)

    async def _on_user_update(self, event: Any) -> None:
        if event.chat_id is None or event.action is None:
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
        try:
            user = await event.get_user()
            if user is not None:
                user_name = self._entity_title(user, int(event.user_id or 0))
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
        if event.chat_id is None:
            return
        for message_id in event.deleted_ids:
            chat_id = int(event.chat_id)
            await self.store.mark_deleted(chat_id, int(message_id))
            await self.events.publish(
                {
                    "type": "MESSAGE_DELETED",
                    "data": {"chat_id": chat_id, "message_id": int(message_id)},
                }
            )

    async def _on_reaction(self, update: Any) -> None:
        if self.client is None:
            return
        try:
            chat_id = int(utils.get_peer_id(update.peer))
            value = await self.client.get_messages(chat_id, ids=int(update.msg_id))
            if value is None:
                return
            message = self._message_model(value, chat_id)
            await self.store.upsert_message(message)
            await self.events.publish(
                {"type": "MESSAGE_EDITED", "data": message.model_dump(mode="json")}
            )
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
            return self.transport.add_proxy_link(link)
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
            await self.events.publish({"type": "READY", "data": self.status.model_dump(mode="json")})
        return {
            "selected_index": index,
            "active_route": self.status.active_route,
            "connected": self.status.connected,
        }

    async def probe_proxies(self) -> list[dict]:
        routes = self.transport.load()

        async def probe_one(index: int, route: ProxyRoute) -> dict:
            try:
                latency = await self.transport.probe(route, timeout=1.8)
                return {"index": index, "available": True, "latency_ms": latency}
            except Exception:
                return {"index": index, "available": False, "latency_ms": None}

        return await asyncio.gather(*(probe_one(index, route) for index, route in enumerate(routes, 1)))

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

    async def chat_info(self, chat_id: int) -> ChatInfo:
        client = self._require_authorized()
        entity = await client.get_entity(chat_id)
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
        entity = await client.get_entity(chat_id)
        if not getattr(entity, "photo", None):
            raise DesktopError("Chat photo is not available")

        root = self.settings.data_root / "avatars"
        root.mkdir(parents=True, exist_ok=True)
        target = chat_photo_path(root, chat_id)
        if not is_fresh_chat_photo(target):
            downloaded = await client.download_profile_photo(entity, file=str(target))
            if downloaded is None or not target.is_file():
                raise DesktopError("Chat photo download failed")

        return DownloadedMedia(
            path=target,
            filename=target.name,
            mime_type="image/jpeg",
        )

    async def download_media(self, chat_id: int, message_id: int) -> DownloadedMedia:
        client = self._require_authorized()
        message = await client.get_messages(chat_id, ids=message_id)
        if message is None or not getattr(message, "media", None):
            raise DesktopError("Media is not available for this message")

        file_info = getattr(message, "file", None)
        mime_type = getattr(file_info, "mime_type", None)
        raw_name = getattr(file_info, "name", None)
        if not raw_name:
            extension = mimetypes.guess_extension(mime_type or "") or ""
            raw_name = f"media_{message_id}{extension}"
        filename = safe_media_name(raw_name, fallback=f"media_{message_id}")

        root = self.settings.data_root / "downloads"
        root.mkdir(parents=True, exist_ok=True)
        target = media_path(root, chat_id, message_id, filename)
        if not target.is_file() or target.stat().st_size == 0:
            downloaded = await client.download_media(message, file=str(target))
            if downloaded is None or not target.is_file():
                raise DesktopError("Media download failed")

        return DownloadedMedia(
            path=target,
            filename=filename,
            mime_type=mime_type or mimetypes.guess_type(filename)[0],
        )

    async def list_dialogs(self, search: str | None = None) -> list[Dialog]:
        client = self._require_authorized()
        dialogs = []
        async for item in client.iter_dialogs():
            value = self._dialog_model(item)
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
            if search and search.casefold() not in value.title.casefold() and not (
                value.username and search.casefold() in value.username.casefold()
            ):
                continue
            dialogs.append(value)
            if "اتاق" in value.title:
                self._priority_chat_ids.add(value.chat_id)
            else:
                self._priority_chat_ids.discard(value.chat_id)
            await self.store.upsert_dialog(value)
        return sorted(
            dialogs,
            key=lambda value: (
                not value.pinned,
                -(value.last_message_at.timestamp() if value.last_message_at else 0),
            ),
        )

    async def list_dialog_folders(self) -> list[DialogFolder]:
        client = self._require_authorized()
        dialogs = await self.list_dialogs()
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

            ordered_ids = [item.chat_id for item in dialogs if any(value.chat_id == item.chat_id for value in values)]
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

    async def history(self, chat_id: int, limit: int = 50, offset_id: int = 0) -> list[Message]:
        if limit < 1 or limit > 200:
            raise ValueError("limit must be between 1 and 200")
        client = self._require_authorized()
        values = []
        async for item in client.iter_messages(
            chat_id,
            limit=limit,
            offset_id=offset_id or 0,
        ):
            value = self._message_model(item, chat_id)
            values.append(value)
            await self.store.upsert_message(value)
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
            message = self._message_model(item, chat_id)
            messages.append(message)
            await self.store.upsert_message(message)
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

    async def send_login_code(self, phone: str) -> dict:
        if self.client is None or not self.status.connected:
            await self._connect()
        if self.client is None or not self.status.connected:
            raise DesktopError("Telegram connection is unavailable")
        if self.status.authorized:
            raise DesktopError("Log out before authorizing another account")
        try:
            sent = await self.client.send_code_request(phone.strip())
        except Exception as error:
            self._log_auth_error(error)
            raise self._auth_error(error, "ارسال کد تأیید انجام نشد.") from None
        self.login_phone = phone.strip()
        self.login_code_hash = sent.phone_code_hash
        self.status = self.status.model_copy(update={"state": "AUTH_REQUIRED", "last_error": None})
        return {"code_sent": True, "requires_2fa": False}

    async def verify_code(self, code: str) -> dict:
        if self.client is None or not self.login_phone or not self.login_code_hash:
            raise DesktopError("Request a new login code")
        try:
            await self.client.sign_in(
                phone=self.login_phone,
                code=code.strip(),
                phone_code_hash=self.login_code_hash,
            )
        except SessionPasswordNeededError:
            return {"code_sent": True, "requires_2fa": True, "authorized": False}
        except Exception as error:
            self._log_auth_error(error)
            raise self._auth_error(error, "تأیید کد انجام نشد.") from None
        await self._mark_authorized()
        self._clear_login_challenge()
        return {"code_sent": True, "requires_2fa": False, "authorized": True}

    async def verify_password(self, password: str) -> dict:
        if self.client is None:
            raise DesktopError("Request a new login code")
        try:
            await self.client.sign_in(password=password)
        except Exception as error:
            self._log_auth_error(error)
            raise self._auth_error(error, "تأیید رمز دومرحله‌ای انجام نشد.") from None
        await self._mark_authorized()
        self._clear_login_challenge()
        return {"code_sent": True, "requires_2fa": False, "authorized": True}

    async def logout(self) -> None:
        self._unregister_handlers()
        if self.client is not None:
            try:
                await self.client.log_out()
            except Exception:
                logger.warning("Telegram logout request failed")
            await self.client.disconnect()
        self.client = None
        if self.route is not None:
            await self.route.deactivate()
        self.route = None
        self.login_phone = None
        self.login_code_hash = None
        self.sessions.remove_client_session()
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
        self._unregister_handlers()
        if self.client is not None:
            await self.client.disconnect()
        self.client = None
        if self.route is not None:
            await self.route.deactivate()
        self.route = None
        self.status = self.status.model_copy(update={"connected": False, "state": "STOPPED"})
