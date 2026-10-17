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
    service._recent_message_chat = {}
    service.relay = None
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
    for chat_id, message_id in ((7, 11), (8, 12)):
        await store.upsert_message(
            Message(chat_id=chat_id, message_id=message_id, text="x", date=datetime(2026, 1, 1, tzinfo=timezone.utc))
        )
    service = build_service(store)

    await service._on_delete(SimpleNamespace(chat_id=None, deleted_ids=[11, 12, 99]))

    deleted = sorted((packet["data"]["chat_id"], packet["data"]["message_id"]) for packet in service.events.packets)
    assert deleted == [(7, 11), (8, 12)]
    assert (await store.history(7, limit=10))[0].deleted is True
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
async def test_login_code_retries_after_proxy_drops_the_request():
    class DroppingClient:
        calls = 0

        def is_connected(self):
            return True

        async def send_code_request(self, phone):
            DroppingClient.calls += 1
            if DroppingClient.calls == 1:
                # What Telethon raises when the connection dies mid-request.
                raise asyncio.CancelledError()
            return SimpleNamespace(phone_code_hash="hash")

    service = build_service(None)
    service.client = DroppingClient()
    service.status = ClientStatus(configured=True, connected=True, authorized=False, state="AUTH_REQUIRED")
    reconnects = []

    async def reconnect():
        reconnects.append(True)

    service._reconnect_unauthorized = reconnect

    result = await service.send_login_code("+989120000000")

    assert result["code_sent"] is True
    assert service.login_code_hash == "hash"
    assert reconnects == [True]
