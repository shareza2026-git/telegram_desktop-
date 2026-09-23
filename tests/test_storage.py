from datetime import datetime, timezone

import pytest

from app.models import Dialog, Message
from app.storage import ChatStore


@pytest.mark.asyncio
async def test_mark_dialog_read_clears_local_unread(tmp_path):
    store = ChatStore(tmp_path / "client.db")
    await store.initialize()
    await store.upsert_dialog(
        Dialog(
            chat_id=7,
            title="Test chat",
            dialog_type="user",
            unread_count=4,
        )
    )

    await store.mark_dialog_read(7)

    dialogs = await store.list_dialogs()
    assert dialogs[0].unread_count == 0


@pytest.mark.asyncio
async def test_history_supports_older_pages(tmp_path):
    store = ChatStore(tmp_path / "client.db")
    await store.initialize()
    for message_id in (1, 2, 3):
        await store.upsert_message(
            Message(
                chat_id=7,
                message_id=message_id,
                text=f"message {message_id}",
                date=datetime(2026, 1, message_id, tzinfo=timezone.utc),
            )
        )

    latest = await store.history(7, limit=2)
    older = await store.history(7, limit=2, offset_id=latest[0].message_id)

    assert [item.message_id for item in latest] == [2, 3]
    assert [item.message_id for item in older] == [1]
