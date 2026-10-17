import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from telethon import types

from app.models import ClientStatus, Message
from app.storage import ChatStore
from app.telegram.service import EventBroker, TelegramDesktopService


class RecordingEvents:
    def __init__(self) -> None:
        self.packets = []

    async def publish(self, packet: dict) -> None:
        self.packets.append(packet)


def build_service(store) -> TelegramDesktopService:
    service = object.__new__(TelegramDesktopService)
    service.client = None
    service.status = ClientStatus(configured=True, connected=True, authorized=True, state="CONNECTED")
    service.store = store
    service.events = RecordingEvents()
    service._outbox_read_max = {}
    service._init_runtime_state()
    return service


@pytest.mark.asyncio
async def test_broker_overflow_keeps_subscriber_alive():
    broker = EventBroker()
    queue = broker.subscribe()
    for index in range(2001):
        await broker.publish({"type": "MESSAGE_NEW", "data": {"index": index}})

    assert queue.get_nowait() == {"type": "RESYNC", "data": {}}
    await broker.publish({"type": "MESSAGE_NEW", "data": {"index": "after"}})
    assert queue.get_nowait()["data"] == {"index": "after"}


@pytest.mark.asyncio
async def test_private_chat_delete_without_chat_id_is_routed_from_cache(tmp_path):
    store = ChatStore(tmp_path / "client.db")
    await store.initialize()
    for chat_id, message_id in ((7, 11), (8, 12), (-1001234567890, 11)):
        await store.upsert_message(
            Message(
                chat_id=chat_id,
                message_id=message_id,
                text="x",
                date=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
        )
    service = build_service(store)

    await service._on_delete(SimpleNamespace(chat_id=None, deleted_ids=[11, 12, 99]))

    deleted = sorted(
        (packet["data"]["chat_id"] or 0, packet["data"]["message_id"])
        for packet in service.events.packets
    )
    # The channel's own message 11 is untouched; unknown ids go out without a chat.
    assert deleted == [(0, 99), (7, 11), (8, 12)]
    history = await store.history(7, limit=10)
    assert history[0].deleted is True
    channel = await store.history(-1001234567890, limit=10)
    assert channel[0].deleted is False
    await store.close()


@pytest.mark.asyncio
async def test_reaction_update_is_published_without_refetching_message(tmp_path):
    store = ChatStore(tmp_path / "client.db")
    await store.initialize()
    service = build_service(store)
    reaction = SimpleNamespace(emoticon="👍")
    update = SimpleNamespace(
        peer=types.PeerUser(user_id=7),
        msg_id=5,
        reactions=SimpleNamespace(
            min=False,
            results=[SimpleNamespace(reaction=reaction, count=2, chosen_order=None)],
        ),
    )

    await service._on_reaction(update)

    packet = service.events.packets[-1]
    assert packet["type"] == "MESSAGE_REACTIONS"
    assert packet["data"]["message_id"] == 5
    assert packet["data"]["reactions"] == [{"emoji": "👍", "count": 2, "chosen": False}]
    await store.close()


@pytest.mark.asyncio
async def test_cached_history_and_dialogs_come_from_store(tmp_path):
    store = ChatStore(tmp_path / "client.db")
    await store.initialize()
    service = build_service(store)
    await store.upsert_messages(
        [
            Message(chat_id=7, message_id=index, text=str(index), date=datetime(2026, 1, index, tzinfo=timezone.utc))
            for index in (1, 2, 3)
        ]
    )

    values = await service.history(7, limit=2, cached=True)

    assert [item.message_id for item in values] == [2, 3]
    assert await service.list_dialogs(cached=True) == []
    await store.close()


@pytest.mark.asyncio
async def test_concurrent_media_requests_share_one_download():
    service = build_service(None)
    calls = 0

    async def slow():
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        return "done"

    results = await asyncio.gather(*(service._single_flight("k", slow) for _ in range(5)))

    assert results == ["done"] * 5
    assert calls == 1
