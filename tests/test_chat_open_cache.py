import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.models import ClientStatus, Dialog, Message
from app.telegram.service import TelegramDesktopService


class FakeEntity:
    first_name = "Cache"
    last_name = "User"
    username = "cache_user"
    participants_count = None
    status = None
    bot = False
    verified = False
    scam = False
    fake = False
    photo = None


class FakeClient:
    def __init__(self):
        self.entity_calls = 0
        self.pinned_calls = 0
        self.iter_calls = 0

    async def get_entity(self, chat_id: int):
        self.entity_calls += 1
        return FakeEntity()

    async def get_messages(self, chat_id: int, limit=None, filter=None):
        self.pinned_calls += 1
        return []

    async def iter_messages(self, chat_id: int, limit: int, offset_id: int = 0):
        self.iter_calls += 1
        yield SimpleNamespace(
            id=5,
            raw_text="remote",
            date=datetime.now(timezone.utc),
            sender_id=1,
            sender=None,
            post_author=None,
            out=False,
            reply_to_msg_id=None,
            media=None,
            reactions=None,
        )


class FakeStore:
    def __init__(self, history_values=None):
        self.history_values = history_values or []
        self.saved = []

    async def history(self, chat_id: int, limit: int, offset_id: int = 0):
        return list(self.history_values)

    async def upsert_message(self, message):
        self.saved.append(message)

    async def upsert_messages(self, messages):
        self.saved.extend(messages)


def build_service(client, store):
    service = TelegramDesktopService.__new__(TelegramDesktopService)
    service.client = client
    service.store = store
    service.status = ClientStatus(
        configured=True,
        connected=True,
        authorized=True,
        state="CONNECTED",
    )
    service._outbox_read_max = {}
    service._dialog_snapshot = []
    return service


@pytest.mark.asyncio
async def test_chat_info_uses_short_ttl_cache():
    client = FakeClient()
    service = build_service(client, FakeStore())

    first = await service.chat_info(7)
    second = await service.chat_info(7)

    assert first == second
    assert client.entity_calls == 1


@pytest.mark.asyncio
async def test_pinned_message_caches_empty_result():
    client = FakeClient()
    service = build_service(client, FakeStore())

    assert await service.pinned_message(7) is None
    assert await service.pinned_message(7) is None
    assert client.pinned_calls == 1


@pytest.mark.asyncio
async def test_history_uses_local_cache_when_latest_id_matches_dialog():
    cached = Message(
        chat_id=7,
        message_id=5,
        text="cached",
        date=datetime.now(timezone.utc),
    )
    client = FakeClient()
    store = FakeStore([cached])
    service = build_service(client, store)
    service._dialog_snapshot = [
        Dialog(
            chat_id=7,
            title="Seven",
            dialog_type="channel",
            unread_count=0,
            pinned=False,
            archived=False,
            muted=False,
            last_message_id=5,
        )
    ]

    values = await service.history(7, limit=80)

    assert [item.message_id for item in values] == [5]
    assert client.iter_calls == 0


@pytest.mark.asyncio
async def test_history_falls_back_to_telegram_when_local_cache_is_stale():
    cached = Message(
        chat_id=7,
        message_id=4,
        text="cached",
        date=datetime.now(timezone.utc),
    )
    client = FakeClient()
    store = FakeStore([cached])
    service = build_service(client, store)
    service._dialog_snapshot = [
        Dialog(
            chat_id=7,
            title="Seven",
            dialog_type="channel",
            unread_count=0,
            pinned=False,
            archived=False,
            muted=False,
            last_message_id=5,
        )
    ]

    values = await service.history(7, limit=80)

    assert [item.message_id for item in values] == [5]
    assert client.iter_calls == 1
