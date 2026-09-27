"""Read selected primary chats and publish through a second account."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import time
from collections import OrderedDict
from contextlib import suppress
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Any

from telethon.errors import SessionPasswordNeededError

from app.models import DesktopError
from app.telegram.client import build_client
from app.telegram.transport import ProxyRoute, TransportCatalog

if TYPE_CHECKING:
    from app.config import Settings
    from app.telegram.service import TelegramDesktopService


logger = logging.getLogger(__name__)


class RelayStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path), timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    async def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(self._initialize)

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS relay_mappings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_chat_id INTEGER NOT NULL,
                    destination_chat_id INTEGER NOT NULL,
                    source_title TEXT NOT NULL,
                    destination_title TEXT NOT NULL,
                    UNIQUE(source_chat_id, destination_chat_id)
                );
                CREATE TABLE IF NOT EXISTS relay_deliveries (
                    mapping_id INTEGER NOT NULL REFERENCES relay_mappings(id) ON DELETE CASCADE,
                    source_message_id INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    destination_message_id INTEGER,
                    error_code TEXT,
                    PRIMARY KEY(mapping_id, source_message_id)
                );
                CREATE INDEX IF NOT EXISTS ix_relay_deliveries_status
                    ON relay_deliveries(status, mapping_id, source_message_id);
                CREATE TABLE IF NOT EXISTS relay_source_deletions (
                    source_chat_id INTEGER NOT NULL,
                    source_message_id INTEGER NOT NULL,
                    PRIMARY KEY(source_chat_id, source_message_id)
                );
            """)

    async def mappings(self) -> list[dict]:
        return await asyncio.to_thread(self._mappings)

    def _mappings(self) -> list[dict]:
        with self._connect() as connection:
            return [dict(row) for row in connection.execute(
                "SELECT id, source_chat_id, destination_chat_id, source_title, destination_title "
                "FROM relay_mappings ORDER BY id"
            )]

    async def add_mapping(self, source_id: int, destination_id: int, source_title: str, destination_title: str) -> dict:
        return await asyncio.to_thread(self._add_mapping, source_id, destination_id, source_title, destination_title)

    def _add_mapping(self, source_id: int, destination_id: int, source_title: str, destination_title: str) -> dict:
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO relay_mappings "
                "(source_chat_id, destination_chat_id, source_title, destination_title) VALUES (?, ?, ?, ?)",
                (source_id, destination_id, source_title, destination_title),
            )
            row = connection.execute(
                "SELECT id, source_chat_id, destination_chat_id, source_title, destination_title "
                "FROM relay_mappings WHERE source_chat_id=? AND destination_chat_id=?",
                (source_id, destination_id),
            ).fetchone()
            return dict(row)

    async def remove_mapping(self, mapping_id: int) -> bool:
        return await asyncio.to_thread(self._remove_mapping, mapping_id)

    def _remove_mapping(self, mapping_id: int) -> bool:
        with self._connect() as connection:
            return bool(connection.execute("DELETE FROM relay_mappings WHERE id=?", (mapping_id,)).rowcount)

    async def enqueue(self, source_id: int, message_id: int) -> int:
        return await asyncio.to_thread(self._enqueue, source_id, message_id)

    def _enqueue(self, source_id: int, message_id: int) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT OR IGNORE INTO relay_deliveries(mapping_id, source_message_id) "
                "SELECT id, ? FROM relay_mappings WHERE source_chat_id=? "
                "AND NOT EXISTS (SELECT 1 FROM relay_source_deletions "
                "WHERE source_chat_id=? AND source_message_id=?)",
                (message_id, source_id, source_id, message_id),
            )
            return max(cursor.rowcount, 0)

    async def mark_source_deleted(self, source_id: int, message_id: int) -> int:
        return await asyncio.to_thread(self._mark_source_deleted, source_id, message_id)

    def _mark_source_deleted(self, source_id: int, message_id: int) -> int:
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO relay_source_deletions(source_chat_id, source_message_id) VALUES (?, ?)",
                (source_id, message_id),
            )
            cursor = connection.execute(
                "UPDATE relay_deliveries SET status=CASE "
                "WHEN status='deleted' THEN 'deleted' "
                "WHEN destination_message_id IS NOT NULL AND status IN ('sent', 'delete_pending', 'delete_failed') THEN 'delete_pending' "
                "ELSE 'source_deleted' END, error_code=NULL "
                "WHERE source_message_id=? AND mapping_id IN "
                "(SELECT id FROM relay_mappings WHERE source_chat_id=?)",
                (message_id, source_id),
            )
            return max(cursor.rowcount, 0)

    async def is_source_deleted(self, source_id: int, message_id: int) -> bool:
        return await asyncio.to_thread(self._is_source_deleted, source_id, message_id)

    def _is_source_deleted(self, source_id: int, message_id: int) -> bool:
        with self._connect() as connection:
            return connection.execute(
                "SELECT 1 FROM relay_source_deletions WHERE source_chat_id=? AND source_message_id=?",
                (source_id, message_id),
            ).fetchone() is not None

    async def next_pending(self) -> dict | None:
        return await asyncio.to_thread(self._next_pending)

    def _next_pending(self) -> dict | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT d.mapping_id, d.source_message_id, m.source_chat_id, m.destination_chat_id "
                "FROM relay_deliveries d JOIN relay_mappings m ON m.id=d.mapping_id "
                "WHERE d.status='pending' ORDER BY d.rowid LIMIT 1"
            ).fetchone()
            return dict(row) if row else None

    async def next_delete_pending(self) -> dict | None:
        return await asyncio.to_thread(self._next_delete_pending)

    def _next_delete_pending(self) -> dict | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT d.mapping_id, d.source_message_id, d.destination_message_id, m.destination_chat_id "
                "FROM relay_deliveries d JOIN relay_mappings m ON m.id=d.mapping_id "
                "WHERE d.status='delete_pending' AND d.destination_message_id IS NOT NULL "
                "ORDER BY d.rowid LIMIT 1"
            ).fetchone()
            return dict(row) if row else None

    async def finish(self, mapping_id: int, message_id: int, status: str, destination_message_id: int | None = None, error_code: str | None = None) -> bool:
        return await asyncio.to_thread(self._finish, mapping_id, message_id, status, destination_message_id, error_code)

    def _finish(self, mapping_id: int, message_id: int, status: str, destination_message_id: int | None, error_code: str | None) -> bool:
        with self._connect() as connection:
            if status == "sent":
                connection.execute(
                    "UPDATE relay_deliveries SET status=CASE "
                    "WHEN EXISTS (SELECT 1 FROM relay_source_deletions s JOIN relay_mappings m "
                    "ON m.source_chat_id=s.source_chat_id WHERE m.id=? AND s.source_message_id=?) "
                    "THEN 'delete_pending' ELSE 'sent' END, destination_message_id=?, error_code=NULL "
                    "WHERE mapping_id=? AND source_message_id=?",
                    (mapping_id, message_id, destination_message_id, mapping_id, message_id),
                )
            else:
                connection.execute(
                    "UPDATE relay_deliveries SET status=CASE WHEN status='source_deleted' "
                    "THEN status ELSE ? END, error_code=? "
                    "WHERE mapping_id=? AND source_message_id=?",
                    (status, error_code, mapping_id, message_id),
                )
            row = connection.execute(
                "SELECT status FROM relay_deliveries WHERE mapping_id=? AND source_message_id=?",
                (mapping_id, message_id),
            ).fetchone()
            return bool(row and row["status"] == "delete_pending")

    async def finish_delete(self, mapping_id: int, message_id: int, success: bool, error_code: str | None = None) -> None:
        await asyncio.to_thread(self._finish_delete, mapping_id, message_id, success, error_code)

    def _finish_delete(self, mapping_id: int, message_id: int, success: bool, error_code: str | None) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE relay_deliveries SET status=?, error_code=? "
                "WHERE mapping_id=? AND source_message_id=? AND status='delete_pending'",
                ("deleted" if success else "delete_failed", error_code, mapping_id, message_id),
            )

    async def counts(self) -> dict[str, int]:
        return await asyncio.to_thread(self._counts)

    def _counts(self) -> dict[str, int]:
        with self._connect() as connection:
            rows = connection.execute("SELECT status, COUNT(*) AS count FROM relay_deliveries GROUP BY status")
            return {str(row["status"]): int(row["count"]) for row in rows}

    async def retry_failed(self) -> int:
        return await asyncio.to_thread(self._retry_failed)

    def _retry_failed(self) -> int:
        with self._connect() as connection:
            sent = connection.execute(
                "UPDATE relay_deliveries SET status='pending', error_code=NULL WHERE status='failed'"
            ).rowcount
            deleted = connection.execute(
                "UPDATE relay_deliveries SET status='delete_pending', error_code=NULL WHERE status='delete_failed'"
            ).rowcount
            return sent + deleted

    async def clear(self) -> None:
        await asyncio.to_thread(self._clear)

    def _clear(self) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM relay_mappings")
            connection.execute("DELETE FROM relay_source_deletions")


class RelayService:
    def __init__(self, settings: Settings, primary: TelegramDesktopService, transport: TransportCatalog) -> None:
        self.settings = settings
        self.primary = primary
        self.transport = transport
        self.store = RelayStore(settings.data_root / "relay.sqlite3")
        self.session_path = settings.data_root / "accounts" / "destination" / "client.session"
        self.client: Any | None = None
        self.route: ProxyRoute | None = None
        self.authorized = False
        self.display_name: str | None = None
        self.phone: str | None = None
        self.code_hash: str | None = None
        self.last_error: str | None = None
        self.last_delivery_ms: int | None = None
        self._connect_lock = asyncio.Lock()
        self._wake = asyncio.Event()
        self._delete_wake = asyncio.Event()
        self._worker: asyncio.Task | None = None
        self._delete_worker: asyncio.Task | None = None
        self._startup: asyncio.Task | None = None
        self._source_ids: set[int] = set()
        self._recent_messages: OrderedDict[tuple[int, int], tuple[Any, float]] = OrderedDict()

    async def start(self) -> None:
        await self.store.initialize()
        self._source_ids = {item["source_chat_id"] for item in await self.store.mappings()}
        self._worker = asyncio.create_task(self._work())
        self._delete_worker = asyncio.create_task(self._delete_work())
        if self.session_path.is_file():
            self._startup = asyncio.create_task(self._restore())

    async def _restore(self) -> None:
        try:
            await self.connect()
            self._wake.set()
            self._delete_wake.set()
        except Exception as error:
            self.last_error = type(error).__name__
            logger.warning("Destination account could not reconnect: %s", type(error).__name__)

    def _candidate_routes(self) -> list[ProxyRoute | None]:
        routes = self.transport.load()
        selected = self.transport.selected_index()
        if selected == 0:
            return [None, *routes]
        if selected is not None and 1 <= selected <= len(routes):
            return [routes[selected - 1], *(route for index, route in enumerate(routes, 1) if index != selected), None]
        return [*routes, None]

    async def connect(self) -> None:
        if not self.settings.telegram_configured:
            raise DesktopError("Telegram API credentials are not configured")
        async with self._connect_lock:
            if self.client is not None and self.client.is_connected():
                return
            if self.client is not None:
                with suppress(Exception):
                    await self.client.disconnect()
            if self.route is not None:
                with suppress(Exception):
                    await self.route.deactivate()
            self.client = None
            self.route = None
            self.authorized = False
            self.display_name = None
            self.session_path.parent.mkdir(parents=True, exist_ok=True)
            for route in self._candidate_routes():
                candidate = None
                try:
                    options = await route.activate() if route else {}
                    candidate = build_client(
                        self.settings,
                        {**options, "receive_updates": False},
                        session=str(self.session_path),
                    )
                    await asyncio.wait_for(candidate.connect(), timeout=12)
                    self.client = candidate
                    self.route = route
                    self.authorized = await asyncio.wait_for(candidate.is_user_authorized(), timeout=8)
                    if self.authorized:
                        account = await asyncio.wait_for(candidate.get_me(), timeout=8)
                        if self.primary.status.user_id == account.id:
                            self.authorized = False
                            with suppress(Exception):
                                await candidate.log_out()
                            raise DesktopError("اکانت دوم باید با اکانت اول متفاوت باشد.")
                        self.display_name = " ".join(filter(None, [account.first_name, account.last_name]))
                    self.last_error = None
                    return
                except Exception as error:
                    logger.warning("Destination route failed: %s", type(error).__name__)
                    if candidate is not None:
                        with suppress(Exception):
                            await candidate.disconnect()
                    if route is not None:
                        with suppress(Exception):
                            await route.deactivate()
                    self.client = None
                    self.route = None
                    if isinstance(error, DesktopError):
                        raise
            raise DesktopError("اتصال اکانت دوم از مسیرهای موجود برقرار نشد.")

    async def status(self) -> dict:
        counts = await self.store.counts()
        return {
            "configured": self.settings.telegram_configured,
            "connected": bool(self.client and self.client.is_connected()),
            "authorized": self.authorized,
            "display_name": self.display_name,
            "pending": counts.get("pending", 0),
            "sent": counts.get("sent", 0),
            "failed": counts.get("failed", 0),
            "blocked": counts.get("blocked", 0),
            "delete_pending": counts.get("delete_pending", 0),
            "deleted": counts.get("deleted", 0),
            "delete_failed": counts.get("delete_failed", 0),
            "last_delivery_ms": self.last_delivery_ms,
            "last_error": self.last_error,
        }

    async def send_code(self, phone: str) -> dict:
        await self.connect()
        if self.authorized:
            raise DesktopError("اکانت دوم قبلاً وارد شده است.")
        try:
            sent = await self.client.send_code_request(phone.strip())
        except Exception as error:
            logger.warning("Destination code request failed: %s", type(error).__name__)
            raise DesktopError("ارسال کد اکانت دوم انجام نشد.") from None
        self.phone = phone.strip()
        self.code_hash = sent.phone_code_hash
        return {"code_sent": True, "requires_2fa": False}

    async def verify_code(self, code: str) -> dict:
        if self.client is None or not self.phone or not self.code_hash:
            raise DesktopError("ابتدا کد اکانت دوم را درخواست کنید.")
        try:
            account = await asyncio.wait_for(
                self.client.sign_in(phone=self.phone, code=code.strip(), phone_code_hash=self.code_hash),
                timeout=20,
            )
        except SessionPasswordNeededError:
            return {"code_sent": True, "requires_2fa": True, "authorized": False}
        except Exception as error:
            logger.warning("Destination code verification failed: %s", type(error).__name__)
            account = await self._recover_authorized()
            if account is None:
                raise DesktopError("تأیید کد اکانت دوم انجام نشد.") from None
        return await self._mark_authorized(account)

    async def verify_password(self, password: str) -> dict:
        if self.client is None:
            raise DesktopError("ابتدا کد اکانت دوم را درخواست کنید.")
        try:
            account = await asyncio.wait_for(self.client.sign_in(password=password), timeout=20)
        except Exception as error:
            logger.warning("Destination password verification failed: %s", type(error).__name__)
            account = await self._recover_authorized()
            if account is None:
                raise DesktopError("تأیید رمز دومرحله‌ای اکانت دوم انجام نشد.") from None
        return await self._mark_authorized(account)

    async def _recover_authorized(self) -> Any | None:
        try:
            if self.client and await self.client.is_user_authorized():
                return await self.client.get_me()
        except Exception:
            pass
        return None

    async def _mark_authorized(self, account: Any) -> dict:
        if self.primary.status.user_id == account.id:
            await self.logout()
            raise DesktopError("اکانت دوم باید با اکانت اول متفاوت باشد.")
        await asyncio.to_thread(self.client.session.save)
        self.authorized = True
        self.display_name = " ".join(filter(None, [account.first_name, account.last_name]))
        self.phone = None
        self.code_hash = None
        self._wake.set()
        self._delete_wake.set()
        return {"code_sent": True, "requires_2fa": False, "authorized": True}

    async def source_channels(self) -> list[dict]:
        dialogs = await self.primary.list_dialogs(force=True)
        return [
            {"chat_id": dialog.chat_id, "title": dialog.title, "dialog_type": dialog.dialog_type}
            for dialog in dialogs if dialog.dialog_type in {"channel", "group", "supergroup"}
        ]

    async def destination_channels(self) -> list[dict]:
        await self._require_authorized()
        result = []
        async for dialog in self.client.iter_dialogs():
            entity = dialog.entity
            if not bool(getattr(entity, "broadcast", False)):
                continue
            rights = getattr(entity, "admin_rights", None)
            if not (getattr(entity, "creator", False) or getattr(rights, "post_messages", False)):
                continue
            result.append({"chat_id": int(dialog.id), "title": str(dialog.title or "")})
        return result

    async def add_mapping(self, source_id: int, destination_id: int) -> dict:
        sources, destinations = await asyncio.gather(self.source_channels(), self.destination_channels())
        source = next((item for item in sources if item["chat_id"] == source_id), None)
        destination = next((item for item in destinations if item["chat_id"] == destination_id), None)
        if source is None or destination is None:
            raise DesktopError("گروه/کانال مبدأ یا کانال مقصد در فهرست حساب مربوطه پیدا نشد.")
        mapping = await self.store.add_mapping(source_id, destination_id, source["title"], destination["title"])
        self._source_ids.add(source_id)
        return mapping

    async def remove_mapping(self, mapping_id: int) -> bool:
        removed = await self.store.remove_mapping(mapping_id)
        if removed:
            self._source_ids = {item["source_chat_id"] for item in await self.store.mappings()}
        return removed

    async def _require_authorized(self) -> Any:
        await self.connect()
        if not self.authorized or self.client is None:
            raise DesktopError("ابتدا اکانت دوم را وارد کنید.")
        return self.client

    async def enqueue(self, source_id: int, message_id: int, message: Any | None = None) -> None:
        if source_id not in self._source_ids:
            return
        if message is not None:
            key = (source_id, message_id)
            self._recent_messages[key] = (message, time.monotonic())
            self._recent_messages.move_to_end(key)
            if len(self._recent_messages) > 512:
                self._recent_messages.popitem(last=False)
        try:
            if await self.store.enqueue(source_id, message_id):
                self._wake.set()
        except Exception as error:
            self.last_error = type(error).__name__
            logger.warning("Relay queue failed: %s", type(error).__name__)

    async def enqueue_delete(self, source_id: int, message_id: int) -> None:
        if source_id not in self._source_ids:
            return
        self._recent_messages.pop((source_id, message_id), None)
        try:
            await self.store.mark_source_deleted(source_id, message_id)
            self._delete_wake.set()
        except Exception as error:
            self.last_error = type(error).__name__
            logger.warning("Relay delete queue failed: %s", type(error).__name__)

    async def retry_failed(self) -> int:
        count = await self.store.retry_failed()
        if count:
            self._wake.set()
            self._delete_wake.set()
        return count

    async def _work(self) -> None:
        while True:
            await self._wake.wait()
            self._wake.clear()
            while True:
                item = await self.store.next_pending()
                if item is None:
                    break
                if not self.authorized:
                    break
                await self._deliver(item)

    async def _delete_work(self) -> None:
        while True:
            await self._delete_wake.wait()
            self._delete_wake.clear()
            while self.authorized:
                item = await self.store.next_delete_pending()
                if item is None:
                    break
                await self._delete_destination(item)

    async def _delete_destination(self, item: dict) -> None:
        try:
            destination = await self._require_authorized()
            await destination.delete_messages(
                item["destination_chat_id"], [item["destination_message_id"]], revoke=True,
            )
            await self.store.finish_delete(item["mapping_id"], item["source_message_id"], True)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.last_error = type(error).__name__
            logger.warning("Relay destination deletion failed: %s", type(error).__name__)
            await self.store.finish_delete(
                item["mapping_id"], item["source_message_id"], False, type(error).__name__,
            )

    async def _deliver(self, item: dict) -> None:
        mapping_id = item["mapping_id"]
        message_id = item["source_message_id"]
        source_id = item["source_chat_id"]
        cached = self._recent_messages.get((source_id, message_id))
        try:
            destination = await self._require_authorized()
            message = cached[0] if cached is not None else await self.primary._require_authorized().get_messages(source_id, ids=message_id)
            if message is None:
                await self.store.finish(mapping_id, message_id, "failed", error_code="SOURCE_MISSING")
                return
            if getattr(message, "noforwards", False):
                await self.store.finish(mapping_id, message_id, "blocked", error_code="CONTENT_PROTECTED")
                return
            if getattr(getattr(message, "chat", None), "noforwards", False):
                await self.store.finish(mapping_id, message_id, "blocked", error_code="CONTENT_PROTECTED")
                return
            if await self.store.is_source_deleted(source_id, message_id):
                return
            text = str(getattr(message, "raw_text", None) or "")
            if getattr(message, "media", None):
                size = int(getattr(getattr(message, "file", None), "size", 0) or 0)
                if size > 100 * 1024 * 1024:
                    await self.store.finish(mapping_id, message_id, "failed", error_code="MEDIA_TOO_LARGE")
                    return
                source = self.primary._require_authorized()
                with TemporaryDirectory(prefix="relay-", dir=self.settings.data_root) as directory:
                    path = await source.download_media(message, file=directory)
                    if not path:
                        raise RuntimeError("MEDIA_DOWNLOAD_FAILED")
                    if await self.store.is_source_deleted(source_id, message_id):
                        return
                    sent = await destination.send_file(item["destination_chat_id"], path, caption=text)
            elif text:
                sent = await destination.send_message(item["destination_chat_id"], text)
            else:
                await self.store.finish(mapping_id, message_id, "blocked", error_code="UNSUPPORTED_MESSAGE")
                return
            if isinstance(sent, list):
                sent = sent[0]
            needs_delete = await self.store.finish(mapping_id, message_id, "sent", destination_message_id=int(sent.id))
            if needs_delete:
                self._delete_wake.set()
            if cached is not None:
                self.last_delivery_ms = round((time.monotonic() - cached[1]) * 1000)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.last_error = type(error).__name__
            logger.warning("Relay delivery failed: %s", type(error).__name__)
            await self.store.finish(mapping_id, message_id, "failed", error_code=type(error).__name__)

    async def logout(self) -> None:
        if self.client is not None:
            with suppress(Exception):
                await self.client.log_out()
            with suppress(Exception):
                await self.client.disconnect()
        if self.route is not None:
            with suppress(Exception):
                await self.route.deactivate()
        self.client = None
        self.route = None
        self.authorized = False
        self.display_name = None
        self.phone = None
        self.code_hash = None
        self.session_path.unlink(missing_ok=True)
        await self.store.clear()
        self._source_ids.clear()
        self._recent_messages.clear()

    async def close(self) -> None:
        for task in (self._startup, self._worker, self._delete_worker):
            if task is not None:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
        if self.client is not None:
            with suppress(Exception):
                await self.client.disconnect()
        if self.route is not None:
            with suppress(Exception):
                await self.route.deactivate()
