from datetime import datetime, timezone

import pytest

from app.models import Message
from app.storage import ChatStore


@pytest.mark.asyncio
async def test_storage_initializes_wal_once_and_keeps_batch_history_working(tmp_path):
    path = tmp_path / "client.db"
    store = ChatStore(path)
    await store.initialize()

    with store._connect() as connection:
        mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
    assert str(mode).lower() == "wal"

    messages = [
        Message(
            chat_id=123,
            message_id=index,
            text=f"message-{index}",
            date=datetime.now(timezone.utc),
        )
        for index in range(1, 6)
    ]
    await store.upsert_messages(messages)

    history = await store.history(123, limit=10)
    assert [item.message_id for item in history] == [1, 2, 3, 4, 5]
