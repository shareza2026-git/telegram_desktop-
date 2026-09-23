import asyncio
import logging
import mimetypes
from datetime import datetime, timezone
from typing import Any

from telethon import TelegramClient, events
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
    DesktopError,
    Dialog,
    MediaInfo,
    Message,
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
        info = self.sessions.info()
        self.status = ClientStatus(
            configured=settings.telegram_configured,
            source_session_available=info.source_available,
            client_session_exists=info.client_exists,
        )

    async def start(self) -> None:
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

    async def _connect(self) -> None:
        routes = self.transport.load()
        candidates: list[ProxyRoute | None] = list(routes)
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
                client = build_client(
                    self.settings,
                    route.options() if route is not None else None,
                )
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
                            "active_route": route.v2ray_name if route else "direct",
                        }
                    )
                return
            except Exception:
                if client is not None:
                    try:
                        await client.disconnect()
                    except Exception:
                        pass

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
                "active_route": self.route.v2ray_name if self.route else "direct",
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
        ]
        for callback, builder in definitions:
            self.client.add_event_handler(callback, builder)
            self.handlers.append((callback, builder))

    def _unregister_handlers(self) -> None:
        if self.client is not None:
            for callback, builder in self.handlers:
                self.client.remove_event_handler(callback, builder)
        self.handlers.clear()

    @staticmethod
    def _as_utc(value: datetime | None) -> datetime:
        if value is None:
            return datetime.now(timezone.utc)
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

    @staticmethod
    def _sender_name(message: Any) -> str | None:
        sender = getattr(message, "sender", None)
        if sender is None:
            return getattr(message, "post_author", None)
        title = getattr(sender, "title", None)
        name = " ".join(filter(None, [getattr(sender, "first_name", None), getattr(sender, "last_name", None)]))
        return name or title or getattr(sender, "username", None) or getattr(message, "post_author", None)

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

    @classmethod
    def _message_model(cls, message: Any, chat_id: int, edited: bool = False) -> Message:
        return Message(
            chat_id=chat_id,
            message_id=int(message.id),
            text=str(getattr(message, "raw_text", None) or ""),
            date=cls._as_utc(getattr(message, "date", None)),
            sender_id=getattr(message, "sender_id", None),
            sender_name=cls._sender_name(message),
            outgoing=bool(getattr(message, "out", False)),
            edited=edited,
            reply_to_message_id=getattr(message, "reply_to_msg_id", None),
            media=cls._media(message),
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
    def _dialog_model(dialog: Any) -> Dialog:
        entity = dialog.entity
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
            last_message_id=getattr(getattr(dialog, "message", None), "id", None),
            last_message_at=getattr(getattr(dialog, "message", None), "date", None),
        )

    async def _on_new(self, event: Any) -> None:
        if event.chat_id is None:
            return
        message = self._message_model(event.message, int(event.chat_id))
        await self.store.upsert_message(message)
        await self.events.publish({"type": "MESSAGE_NEW", "data": message.model_dump(mode="json")})

    async def _on_edit(self, event: Any) -> None:
        if event.chat_id is None:
            return
        message = self._message_model(event.message, int(event.chat_id), edited=True)
        await self.store.upsert_message(message)
        await self.events.publish({"type": "MESSAGE_EDITED", "data": message.model_dump(mode="json")})

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

    def _require_authorized(self) -> TelegramClient:
        if self.client is None or not self.status.connected or not self.status.authorized:
            raise DesktopError("Telegram is not connected and authorized")
        return self.client

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

        root = self.settings.project_root / "data" / "telegram_desktop" / "avatars"
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

        root = self.settings.project_root / "data" / "telegram_desktop" / "downloads"
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
            if search and search.casefold() not in value.title.casefold() and not (
                value.username and search.casefold() in value.username.casefold()
            ):
                continue
            dialogs.append(value)
            await self.store.upsert_dialog(value)
        return sorted(
            dialogs,
            key=lambda value: (
                not value.pinned,
                -(value.last_message_at.timestamp() if value.last_message_at else 0),
            ),
        )

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
        client = self._require_authorized()
        value = await client.send_file(
            chat_id,
            file=path,
            caption=caption or None,
            reply_to=reply_to_message_id,
        )
        if isinstance(value, list):
            if not value:
                raise DesktopError("Telegram did not return the uploaded message")
            value = value[0]

        message = self._message_model(value, chat_id)
        await self.store.upsert_message(message)
        await self.events.publish({"type": "MESSAGE_NEW", "data": message.model_dump(mode="json")})
        return message

    async def edit_text(self, chat_id: int, message_id: int, text: str) -> Message:
        client, _ = await self._own_message(chat_id, message_id)
        value = await client.edit_message(chat_id, message_id, text)
        message = self._message_model(value, chat_id, edited=True)
        await self.store.upsert_message(message)
        await self.events.publish({"type": "MESSAGE_EDITED", "data": message.model_dump(mode="json")})
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
        self._unregister_handlers()
        if self.client is not None:
            await self.client.disconnect()
        self.client = None
        self.status = self.status.model_copy(update={"connected": False, "state": "STOPPED"})
