import asyncio
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from app.models import Dialog, MediaInfo, Message, ReactionSummary


class ChatStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        async with self._lock:
            await asyncio.to_thread(self._initialize_sync)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path), timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    def _initialize_sync(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
            connection.execute("PRAGMA wal_autocheckpoint=1000")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS dialogs (
                    chat_id INTEGER PRIMARY KEY,
                    title TEXT NOT NULL,
                    dialog_type TEXT NOT NULL,
                    username TEXT,
                    unread_count INTEGER NOT NULL DEFAULT 0,
                    pinned INTEGER NOT NULL DEFAULT 0,
                    archived INTEGER NOT NULL DEFAULT 0,
                    muted INTEGER NOT NULL DEFAULT 0,
                    last_message_id INTEGER,
                    last_message_at TEXT,
                    last_message_preview TEXT
                );

                CREATE TABLE IF NOT EXISTS messages (
                    chat_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL,
                    text TEXT NOT NULL DEFAULT '',
                    date TEXT NOT NULL,
                    sender_id INTEGER,
                    sender_name TEXT,
                    outgoing INTEGER NOT NULL DEFAULT 0,
                    edited INTEGER NOT NULL DEFAULT 0,
                    reply_to_message_id INTEGER,
                    media_json TEXT,
                    reactions_json TEXT,
                    read INTEGER NOT NULL DEFAULT 0,
                    deleted INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (chat_id, message_id)
                );

                CREATE INDEX IF NOT EXISTS ix_messages_chat_date
                ON messages(chat_id, message_id DESC);
                """
            )
            self._ensure_column(connection, "dialogs", "muted", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(connection, "dialogs", "last_message_preview", "TEXT")
            self._ensure_column(connection, "messages", "reactions_json", "TEXT")
            self._ensure_column(connection, "messages", "read", "INTEGER NOT NULL DEFAULT 0")

    @staticmethod
    def _ensure_column(
        connection: sqlite3.Connection,
        table: str,
        column: str,
        declaration: str,
    ) -> None:
        columns = {
            str(row["name"])
            for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in columns:
            connection.execute(
                f"ALTER TABLE {table} ADD COLUMN {column} {declaration}"
            )

    async def upsert_dialog(self, dialog: Dialog) -> None:
        async with self._lock:
            await asyncio.to_thread(self._upsert_dialog_sync, dialog)

    async def upsert_dialogs(self, dialogs: list[Dialog]) -> None:
        if not dialogs:
            return
        async with self._lock:
            await asyncio.to_thread(self._upsert_dialogs_sync, dialogs)

    def _upsert_dialog_sync(self, dialog: Dialog) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO dialogs (
                    chat_id, title, dialog_type, username, unread_count,
                    pinned, archived, muted, last_message_id, last_message_at,
                    last_message_preview
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    title=excluded.title,
                    dialog_type=excluded.dialog_type,
                    username=excluded.username,
                    unread_count=excluded.unread_count,
                    pinned=excluded.pinned,
                    archived=excluded.archived,
                    muted=excluded.muted,
                    last_message_id=excluded.last_message_id,
                    last_message_at=excluded.last_message_at,
                    last_message_preview=excluded.last_message_preview
                """,
                (
                    dialog.chat_id,
                    dialog.title,
                    dialog.dialog_type,
                    dialog.username,
                    dialog.unread_count,
                    int(dialog.pinned),
                    int(dialog.archived),
                    int(dialog.muted),
                    dialog.last_message_id,
                    dialog.last_message_at.isoformat() if dialog.last_message_at else None,
                    dialog.last_message_preview,
                ),
            )

    def _upsert_dialogs_sync(self, dialogs: list[Dialog]) -> None:
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO dialogs (
                    chat_id, title, dialog_type, username, unread_count,
                    pinned, archived, muted, last_message_id, last_message_at,
                    last_message_preview
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    title=excluded.title,
                    dialog_type=excluded.dialog_type,
                    username=excluded.username,
                    unread_count=excluded.unread_count,
                    pinned=excluded.pinned,
                    archived=excluded.archived,
                    muted=excluded.muted,
                    last_message_id=excluded.last_message_id,
                    last_message_at=excluded.last_message_at,
                    last_message_preview=excluded.last_message_preview
                """,
                [
                    (
                        dialog.chat_id,
                        dialog.title,
                        dialog.dialog_type,
                        dialog.username,
                        dialog.unread_count,
                        int(dialog.pinned),
                        int(dialog.archived),
                        int(dialog.muted),
                        dialog.last_message_id,
                        dialog.last_message_at.isoformat() if dialog.last_message_at else None,
                        dialog.last_message_preview,
                    )
                    for dialog in dialogs
                ],
            )

    async def mark_dialog_read(self, chat_id: int) -> None:
        async with self._lock:
            await asyncio.to_thread(self._mark_dialog_read_sync, chat_id)

    def _mark_dialog_read_sync(self, chat_id: int) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE dialogs SET unread_count=0 WHERE chat_id=?",
                (chat_id,),
            )

    async def upsert_message(self, message: Message) -> None:
        async with self._lock:
            await asyncio.to_thread(self._upsert_message_sync, message)

    async def upsert_messages(self, messages: list[Message]) -> None:
        if not messages:
            return
        async with self._lock:
            await asyncio.to_thread(self._upsert_messages_sync, messages)

    def _upsert_message_sync(self, message: Message) -> None:
        media_json = json.dumps(
            message.media.model_dump(mode="json") if message.media else None,
            ensure_ascii=False,
        )
        reactions_json = json.dumps(
            [item.model_dump(mode="json") for item in message.reactions],
            ensure_ascii=False,
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO messages (
                    chat_id, message_id, text, date, sender_id, sender_name,
                    outgoing, edited, reply_to_message_id, media_json,
                    reactions_json, read, deleted
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chat_id, message_id) DO UPDATE SET
                    text=excluded.text,
                    date=excluded.date,
                    sender_id=excluded.sender_id,
                    sender_name=excluded.sender_name,
                    outgoing=excluded.outgoing,
                    edited=excluded.edited,
                    reply_to_message_id=excluded.reply_to_message_id,
                    media_json=excluded.media_json,
                    reactions_json=excluded.reactions_json,
                    read=MAX(messages.read, excluded.read),
                    deleted=excluded.deleted
                """,
                (
                    message.chat_id,
                    message.message_id,
                    message.text,
                    message.date.isoformat(),
                    message.sender_id,
                    message.sender_name,
                    int(message.outgoing),
                    int(message.edited),
                    message.reply_to_message_id,
                    media_json,
                    reactions_json,
                    int(message.read),
                    int(message.deleted),
                ),
            )

    def _upsert_messages_sync(self, messages: list[Message]) -> None:
        rows = []
        for message in messages:
            media_json = json.dumps(
                message.media.model_dump(mode="json") if message.media else None,
                ensure_ascii=False,
            )
            reactions_json = json.dumps(
                [item.model_dump(mode="json") for item in message.reactions],
                ensure_ascii=False,
            )
            rows.append(
                (
                    message.chat_id,
                    message.message_id,
                    message.text,
                    message.date.isoformat(),
                    message.sender_id,
                    message.sender_name,
                    int(message.outgoing),
                    int(message.edited),
                    message.reply_to_message_id,
                    media_json,
                    reactions_json,
                    int(message.read),
                    int(message.deleted),
                )
            )

        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO messages (
                    chat_id, message_id, text, date, sender_id, sender_name,
                    outgoing, edited, reply_to_message_id, media_json,
                    reactions_json, read, deleted
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chat_id, message_id) DO UPDATE SET
                    text=excluded.text,
                    date=excluded.date,
                    sender_id=excluded.sender_id,
                    sender_name=excluded.sender_name,
                    outgoing=excluded.outgoing,
                    edited=excluded.edited,
                    reply_to_message_id=excluded.reply_to_message_id,
                    media_json=excluded.media_json,
                    reactions_json=excluded.reactions_json,
                    read=MAX(messages.read, excluded.read),
                    deleted=excluded.deleted
                """,
                rows,
            )

    async def mark_outgoing_read(self, chat_id: int, max_id: int) -> None:
        async with self._lock:
            await asyncio.to_thread(self._mark_outgoing_read_sync, chat_id, max_id)

    def _mark_outgoing_read_sync(self, chat_id: int, max_id: int) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE messages
                SET read=1
                WHERE chat_id=? AND outgoing=1 AND message_id <= ?
                """,
                (chat_id, max_id),
            )

    async def mark_deleted(self, chat_id: int, message_id: int) -> None:
        async with self._lock:
            await asyncio.to_thread(self._mark_deleted_sync, chat_id, message_id)

    def _mark_deleted_sync(self, chat_id: int, message_id: int) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO messages(chat_id, message_id, text, date, deleted)
                VALUES (?, ?, '', ?, 1)
                ON CONFLICT(chat_id, message_id) DO UPDATE SET
                    text='',
                    media_json=NULL,
                    reactions_json=NULL,
                    deleted=1
                """,
                (chat_id, message_id, datetime.now().astimezone().isoformat()),
            )

    async def find_unique_message_chat(self, message_id: int) -> int | None:
        async with self._lock:
            return await asyncio.to_thread(self._find_unique_message_chat_sync, message_id)

    def _find_unique_message_chat_sync(self, message_id: int) -> int | None:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT chat_id FROM messages
                WHERE message_id=? AND deleted=0
                LIMIT 2
                """,
                (message_id,),
            ).fetchall()
        return int(rows[0]["chat_id"]) if len(rows) == 1 else None

    async def mark_deleted_many(self, chat_id: int, message_ids: list[int]) -> None:
        if not message_ids:
            return
        async with self._lock:
            await asyncio.to_thread(self._mark_deleted_many_sync, chat_id, message_ids)

    def _mark_deleted_many_sync(self, chat_id: int, message_ids: list[int]) -> None:
        now = datetime.now().astimezone().isoformat()
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO messages(chat_id, message_id, text, date, deleted)
                VALUES (?, ?, '', ?, 1)
                ON CONFLICT(chat_id, message_id) DO UPDATE SET
                    text='',
                    media_json=NULL,
                    reactions_json=NULL,
                    deleted=1
                """,
                [(chat_id, int(message_id), now) for message_id in message_ids],
            )

    async def list_dialogs(self, search: str | None = None) -> list[Dialog]:
        async with self._lock:
            return await asyncio.to_thread(self._list_dialogs_sync, search)

    def _list_dialogs_sync(self, search: str | None) -> list[Dialog]:
        with self._connect() as connection:
            if search:
                rows = connection.execute(
                    """
                    SELECT * FROM dialogs
                    WHERE title LIKE ? OR username LIKE ?
                    ORDER BY pinned DESC, last_message_at DESC, title COLLATE NOCASE
                    """,
                    (f"%{search}%", f"%{search}%"),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT * FROM dialogs
                    ORDER BY pinned DESC, last_message_at DESC, title COLLATE NOCASE
                    """
                ).fetchall()
        return [self._dialog_from_row(row) for row in rows]

    async def history(self, chat_id: int, limit: int, offset_id: int = 0) -> list[Message]:
        async with self._lock:
            return await asyncio.to_thread(self._history_sync, chat_id, limit, offset_id)

    def _history_sync(self, chat_id: int, limit: int, offset_id: int) -> list[Message]:
        with self._connect() as connection:
            if offset_id:
                rows = connection.execute(
                    """
                    SELECT * FROM messages
                    WHERE chat_id=? AND message_id < ?
                    ORDER BY message_id DESC LIMIT ?
                    """,
                    (chat_id, offset_id, limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT * FROM messages
                    WHERE chat_id=?
                    ORDER BY message_id DESC LIMIT ?
                    """,
                    (chat_id, limit),
                ).fetchall()
        return [self._message_from_row(row) for row in reversed(rows)]

    @staticmethod
    def _dialog_from_row(row: sqlite3.Row) -> Dialog:
        return Dialog(
            chat_id=row["chat_id"],
            title=row["title"],
            dialog_type=row["dialog_type"],
            username=row["username"],
            unread_count=row["unread_count"],
            pinned=bool(row["pinned"]),
            archived=bool(row["archived"]),
            muted=bool(row["muted"]) if "muted" in row.keys() else False,
            last_message_id=row["last_message_id"],
            last_message_at=(
                datetime.fromisoformat(row["last_message_at"])
                if row["last_message_at"] else None
            ),
            last_message_preview=(
                row["last_message_preview"]
                if "last_message_preview" in row.keys() else None
            ),
        )

    @staticmethod
    def _message_from_row(row: sqlite3.Row) -> Message:
        media_value = json.loads(row["media_json"]) if row["media_json"] else None
        reactions_raw = row["reactions_json"] if "reactions_json" in row.keys() else None
        reactions_value = json.loads(reactions_raw) if reactions_raw else []
        return Message(
            chat_id=row["chat_id"],
            message_id=row["message_id"],
            text=row["text"],
            date=datetime.fromisoformat(row["date"]),
            sender_id=row["sender_id"],
            sender_name=row["sender_name"],
            outgoing=bool(row["outgoing"]),
            edited=bool(row["edited"]),
            reply_to_message_id=row["reply_to_message_id"],
            media=MediaInfo.model_validate(media_value) if media_value else None,
            reactions=[
                ReactionSummary.model_validate(item)
                for item in reactions_value
            ],
            read=bool(row["read"]) if "read" in row.keys() else False,
            deleted=bool(row["deleted"]),
        )

    async def close(self) -> None:
        return None
