import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from telethon import TelegramClient, events
from telethon.errors import SessionPasswordNeededError

from app.config import Settings
from app.models import (
    ClientStatus,
    DesktopError,
    Dialog,
    MediaInfo,
    Message,
)
from app.storage import ChatStore
from app.telegram.client import build_client
from app.telegram.session import SessionManager
from app.telegram.transport import ProxyRoute, TransportCatalog


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
        self.status = ClientStatus(
            configured=settings.telegram_configured,
            source_session_available=self.sessions.info().source_available,
            client_session_exists=self.sessions.info().client_exists,
        )

    async def start(self) -> None:
        self.sessions.ensure_client_path()
        self.status = self.status.model_copy(
            update={
                "configured": self.settings.telegram_configured,
                "source_session_available": self.sessions.info().source_available,
                "client_session_exists": self.sessions.info().client_exists,
            }
        )
        if not self.settings.telegram_configured:
            self.status = self.status.model_copy(update={"state": "UNCONFIGURED"})
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

    async def send_text(self, chat_id: int, text: str) -> Message:
        client = self._require_authorized()
        value = await client.send_message(chat_id, text)
        message = self._message_model(value, chat_id)
        await self.store.upsert_message(message)
        await self.events.publish({"type": "MESSAGE_NEW", "data": message.model_dump(mode="json")})
        return message

    async def send_login_code(self, phone: str) -> dict:
        if self.client is None or not self.status.connected:
            await self._connect()
        if self.client is None or not self.status.connected:
            raise DesktopError("Telegram connection is unavailable")
        if self.status.authorized:
            raise DesktopError("Log out before authorizing another account")
        sent = await self.client.send_code_request(phone.strip())
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
        await self._mark_authorized()
        return {"code_sent": True, "requires_2fa": False, "authorized": True}

    async def verify_password(self, password: str) -> dict:
        if self.client is None:
            raise DesktopError("Request a new login code")
        await self.client.sign_in(password=password)
        await self._mark_authorized()
        return {"code_sent": True, "requires_2fa": False, "authorized": True}

    async def logout(self) -> None:
        self._unregister_handlers()
        if self.client is not None:
            try:
                await self.client.log_out()
            except Exception:
                logging.getLogger(__name__).warning("Telegram logout request failed")
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
