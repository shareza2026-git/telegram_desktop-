import asyncio
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Iterable

from app.models import Dialog, MediaInfo, Message, ReactionSummary


# Channel and supergroup ids are -100xxxxxxxxxx. Their message ids are
# per-channel; every other chat shares one account-wide message id sequence.
CHANNEL_ID_LIMIT = -1_000_000_000_000


class ChatStore:
    """Local cache of dialogs and messages.

    One SQLite connection is kept open for the life of the backend and every
    call runs on a worker thread under a lock, so writes never block the event
    loop and batches go through a single transaction.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = asyncio.Lock()
        self._connection: sqlite3.Connection | None = None

    async def initialize(self) -> None:
        async with self._lock:
            await asyncio.to_thread(self._initialize_sync)

    def _db(self) -> sqlite3.Connection:
        if self._connection is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(str(self.path), timeout=5.0, check_same_thread=False)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
            connection.execute("PRAGMA foreign_keys=ON")
            self._connection = connection
        return self._connection

    async def _run(self, function, *args):
        async with self._lock:
            return await asyncio.to_thread(function, *args)

    def _initialize_sync(self) -> None:
        connection = self._db()
        with connection:
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

                CREATE INDEX IF NOT EXISTS ix_messages_id
                ON messages(message_id);
                """
            )
            self._ensure_column(connection, "dialogs", "muted", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(connection, "dialogs", "last_message_preview", "TEXT")
            self._ensure_column(connection, "dialogs", "last_message_sender", "TEXT")
            self._ensure_column(connection, "dialogs", "last_message_outgoing", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(connection, "dialogs", "last_message_read", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(connection, "dialogs", "sort_order", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(connection, "messages", "reactions_json", "TEXT")
            self._ensure_column(connection, "messages", "read", "INTEGER NOT NULL DEFAULT 0")
            # Everything newer than the original columns (entities, forward
            # header, service action, views, album id) lives in one JSON blob
            # so the schema does not need a migration per Telegram feature.
            self._ensure_column(connection, "messages", "extra_json", "TEXT")

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

    # Dialogs -----------------------------------------------------------------

    _DIALOG_UPSERT = """
        INSERT INTO dialogs (
            chat_id, title, dialog_type, username, unread_count,
            pinned, archived, muted, last_message_id, last_message_at,
            last_message_preview, last_message_sender, last_message_outgoing,
            last_message_read, sort_order
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            last_message_preview=excluded.last_message_preview,
            last_message_sender=excluded.last_message_sender,
            last_message_outgoing=excluded.last_message_outgoing,
            last_message_read=excluded.last_message_read,
            sort_order=excluded.sort_order
    """

    @staticmethod
    def _dialog_row(dialog: Dialog, order: int) -> tuple:
        return (
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
            dialog.last_message_sender,
            int(dialog.last_message_outgoing),
            int(dialog.last_message_read),
            order,
        )

    async def upsert_dialog(self, dialog: Dialog) -> None:
        await self.upsert_dialogs([dialog])

    async def upsert_dialogs(self, dialogs: Iterable[Dialog]) -> None:
        rows = [self._dialog_row(dialog, order) for order, dialog in enumerate(dialogs)]
        if rows:
            await self._run(self._executemany, self._DIALOG_UPSERT, rows)

    async def replace_dialogs(self, dialogs: list[Dialog]) -> None:
        """Store a complete dialog list, dropping chats the account left."""
        rows = [self._dialog_row(dialog, order) for order, dialog in enumerate(dialogs)]
        await self._run(self._replace_dialogs_sync, rows)

    def _replace_dialogs_sync(self, rows: list[tuple]) -> None:
        connection = self._db()
        with connection:
            connection.executemany(self._DIALOG_UPSERT, rows)
            ids = [row[0] for row in rows]
            if ids:
                connection.execute(
                    f"DELETE FROM dialogs WHERE chat_id NOT IN ({','.join('?' * len(ids))})",
                    ids,
                )

    def _executemany(self, sql: str, rows: list[tuple]) -> None:
        connection = self._db()
        with connection:
            connection.executemany(sql, rows)

    def _execute(self, sql: str, values: tuple) -> None:
        connection = self._db()
        with connection:
            connection.execute(sql, values)

    async def mark_dialog_read(self, chat_id: int) -> None:
        await self._run(self._execute, "UPDATE dialogs SET unread_count=0 WHERE chat_id=?", (chat_id,))

    async def list_dialogs(self, search: str | None = None) -> list[Dialog]:
        return await self._run(self._list_dialogs_sync, search)

    def _list_dialogs_sync(self, search: str | None) -> list[Dialog]:
        connection = self._db()
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

    # Messages ----------------------------------------------------------------

    _MESSAGE_UPSERT = """
        INSERT INTO messages (
            chat_id, message_id, text, date, sender_id, sender_name,
            outgoing, edited, reply_to_message_id, media_json,
            reactions_json, read, deleted, extra_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            deleted=excluded.deleted,
            extra_json=excluded.extra_json
    """

    @staticmethod
    def _message_row(message: Message) -> tuple:
        media_json = json.dumps(
            message.media.model_dump(mode="json") if message.media else None,
            ensure_ascii=False,
        )
        reactions_json = json.dumps(
            [item.model_dump(mode="json") for item in message.reactions],
            ensure_ascii=False,
        )
        extra_json = json.dumps(
            message.model_dump(mode="json", include=Message.EXTRA_FIELDS),
            ensure_ascii=False,
        )
        return (
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
            extra_json,
        )

    async def upsert_message(self, message: Message) -> None:
        await self.upsert_messages([message])

    async def upsert_messages(self, messages: Iterable[Message]) -> None:
        rows = [self._message_row(message) for message in messages]
        if rows:
            await self._run(self._executemany, self._MESSAGE_UPSERT, rows)

    async def update_reactions(
        self,
        chat_id: int,
        message_id: int,
        reactions: list[ReactionSummary],
    ) -> None:
        payload = json.dumps([item.model_dump(mode="json") for item in reactions], ensure_ascii=False)
        await self._run(
            self._execute,
            "UPDATE messages SET reactions_json=? WHERE chat_id=? AND message_id=?",
            (payload, chat_id, message_id),
        )

    async def mark_outgoing_read(self, chat_id: int, max_id: int) -> None:
        await self._run(
            self._execute,
            """
            UPDATE messages
            SET read=1
            WHERE chat_id=? AND outgoing=1 AND message_id <= ?
            """,
            (chat_id, max_id),
        )

    async def mark_deleted(self, chat_id: int, message_id: int) -> None:
        await self._run(self._mark_deleted_sync, chat_id, message_id)

    def _mark_deleted_sync(self, chat_id: int, message_id: int) -> None:
        connection = self._db()
        with connection:
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

    async def chats_for_shared_ids(self, message_ids: list[int]) -> dict[int, list[int]]:
        """Map account-wide message ids (private chats and basic groups) to chats.

        Telegram reports deletions there without a chat id, so the local
        cache is the only way to know which open chat they belong to.
        """
        if not message_ids:
            return {}
        return await self._run(self._chats_for_shared_ids_sync, list(message_ids))

    def _chats_for_shared_ids_sync(self, message_ids: list[int]) -> dict[int, list[int]]:
        connection = self._db()
        rows = connection.execute(
            f"""
            SELECT chat_id, message_id FROM messages
            WHERE message_id IN ({','.join('?' * len(message_ids))})
              AND chat_id > ?
            """,
            (*message_ids, CHANNEL_ID_LIMIT),
        ).fetchall()
        result: dict[int, list[int]] = {}
        for row in rows:
            result.setdefault(int(row["chat_id"]), []).append(int(row["message_id"]))
        return result

    async def find_unique_message_chat(self, message_id: int) -> int | None:
        """The one cached chat holding this id, or None if absent or ambiguous."""
        return await self._run(self._find_unique_message_chat_sync, message_id)

    def _find_unique_message_chat_sync(self, message_id: int) -> int | None:
        rows = self._db().execute(
            """
            SELECT chat_id FROM messages
            WHERE message_id=? AND deleted=0
            LIMIT 2
            """,
            (message_id,),
        ).fetchall()
        return int(rows[0]["chat_id"]) if len(rows) == 1 else None

    async def mark_deleted_many(self, chat_id: int, message_ids: list[int]) -> None:
        if message_ids:
            await self._run(self._mark_deleted_many_sync, chat_id, list(message_ids))

    def _mark_deleted_many_sync(self, chat_id: int, message_ids: list[int]) -> None:
        now = datetime.now().astimezone().isoformat()
        connection = self._db()
        with connection:
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

    async def history(self, chat_id: int, limit: int, offset_id: int = 0) -> list[Message]:
        return await self._run(self._history_sync, chat_id, limit, offset_id)

    def _history_sync(self, chat_id: int, limit: int, offset_id: int) -> list[Message]:
        connection = self._db()
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
        keys = row.keys()
        return Dialog(
            chat_id=row["chat_id"],
            title=row["title"],
            dialog_type=row["dialog_type"],
            username=row["username"],
            unread_count=row["unread_count"],
            pinned=bool(row["pinned"]),
            archived=bool(row["archived"]),
            muted=bool(row["muted"]) if "muted" in keys else False,
            last_message_id=row["last_message_id"],
            last_message_at=(
                datetime.fromisoformat(row["last_message_at"])
                if row["last_message_at"] else None
            ),
            last_message_preview=row["last_message_preview"] if "last_message_preview" in keys else None,
            last_message_sender=row["last_message_sender"] if "last_message_sender" in keys else None,
            last_message_outgoing=bool(row["last_message_outgoing"]) if "last_message_outgoing" in keys else False,
            last_message_read=bool(row["last_message_read"]) if "last_message_read" in keys else False,
        )

    @staticmethod
    def _message_from_row(row: sqlite3.Row) -> Message:
        keys = row.keys()
        media_value = json.loads(row["media_json"]) if row["media_json"] else None
        reactions_raw = row["reactions_json"] if "reactions_json" in keys else None
        reactions_value = json.loads(reactions_raw) if reactions_raw else []
        extra_raw = row["extra_json"] if "extra_json" in keys else None
        extra = json.loads(extra_raw) if extra_raw else {}
        if not isinstance(extra, dict):
            extra = {}
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
            read=bool(row["read"]) if "read" in keys else False,
            deleted=bool(row["deleted"]),
            **{key: value for key, value in extra.items() if key in Message.EXTRA_FIELDS},
        )

    async def close(self) -> None:
        async with self._lock:
            if self._connection is not None:
                connection = self._connection
                self._connection = None
                await asyncio.to_thread(connection.close)
