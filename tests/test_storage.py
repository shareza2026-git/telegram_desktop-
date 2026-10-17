from datetime import datetime, timezone

import pytest

from app.models import Dialog, Message, ReactionSummary
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



@pytest.mark.asyncio
async def test_reactions_survive_storage_roundtrip(tmp_path):
    store = ChatStore(tmp_path / "client.db")
    await store.initialize()
    await store.upsert_message(
        Message(
            chat_id=7,
            message_id=9,
            text="reacted",
            date=datetime(2026, 1, 9, tzinfo=timezone.utc),
            reactions=[
                ReactionSummary(emoji="👍", count=3, chosen=True),
                ReactionSummary(emoji="🔥", count=1),
            ],
        )
    )

    values = await store.history(7, limit=10)

    assert [(item.emoji, item.count, item.chosen) for item in values[0].reactions] == [
        ("👍", 3, True),
        ("🔥", 1, False),
    ]



@pytest.mark.asyncio
async def test_outgoing_read_receipts_are_persisted_by_max_id(tmp_path):
    store = ChatStore(tmp_path / "client.db")
    await store.initialize()
    for message_id, outgoing in ((10, True), (11, True), (12, False)):
        await store.upsert_message(
            Message(
                chat_id=7,
                message_id=message_id,
                text="status",
                date=datetime(2026, 1, 10, tzinfo=timezone.utc),
                outgoing=outgoing,
            )
        )

    await store.mark_outgoing_read(7, 10)
    values = await store.history(7, limit=10)

    assert [(item.message_id, item.read) for item in values] == [
        (10, True),
        (11, False),
        (12, False),
    ]


@pytest.mark.asyncio
async def test_extra_message_fields_survive_storage_roundtrip(tmp_path):
    from app.models import LinkPreview, MessageEntity

    store = ChatStore(tmp_path / "client.db")
    await store.initialize()
    await store.upsert_messages(
        [
            Message(
                chat_id=7,
                message_id=1,
                text="bold link",
                date=datetime(2026, 1, 1, tzinfo=timezone.utc),
                entities=[MessageEntity(type="bold", offset=0, length=4)],
                forward_from="Channel",
                grouped_id=55,
                views=10,
                link_preview=LinkPreview(url="https://example.com", title="Example"),
            )
        ]
    )

    value = (await store.history(7, limit=1))[0]

    assert value.entities[0].type == "bold"
    assert value.forward_from == "Channel"
    assert value.grouped_id == 55
    assert value.views == 10
    assert value.link_preview.title == "Example"
    await store.close()


@pytest.mark.asyncio
async def test_replace_dialogs_drops_chats_that_were_left(tmp_path):
    store = ChatStore(tmp_path / "client.db")
    await store.initialize()
    await store.replace_dialogs([Dialog(chat_id=1, title="a", dialog_type="user"), Dialog(chat_id=2, title="b", dialog_type="user")])
    await store.replace_dialogs([Dialog(chat_id=2, title="b", dialog_type="user")])

    assert [item.chat_id for item in await store.list_dialogs()] == [2]
    await store.close()
