from datetime import datetime, timezone

import pytest

from app.models import ClientStatus, DesktopError
from app.telegram.service import TelegramDesktopService


class FakeMessage:
    def __init__(
        self,
        message_id: int,
        text: str,
        *,
        outgoing: bool = True,
        reply_to_message_id: int | None = None,
    ) -> None:
        self.id = message_id
        self.raw_text = text
        self.date = datetime(2026, 9, 23, tzinfo=timezone.utc)
        self.sender_id = 10
        self.sender = None
        self.post_author = None
        self.out = outgoing
        self.reply_to_msg_id = reply_to_message_id
        self.media = None


class FakeClient:
    def __init__(self, existing: FakeMessage | None = None) -> None:
        self.existing = existing
        self.sent: list[tuple[int, str, int | None]] = []
        self.edited: list[tuple[int, int, str]] = []
        self.deleted: list[tuple[int, list[int], bool]] = []

    async def get_messages(self, chat_id: int, ids: int):
        return self.existing

    async def send_message(self, chat_id: int, text: str, reply_to: int | None = None):
        self.sent.append((chat_id, text, reply_to))
        return FakeMessage(20, text, reply_to_message_id=reply_to)

    async def edit_message(self, chat_id: int, message_id: int, text: str):
        self.edited.append((chat_id, message_id, text))
        return FakeMessage(message_id, text)

    async def delete_messages(self, chat_id: int, message_ids: list[int], revoke: bool):
        self.deleted.append((chat_id, message_ids, revoke))


class FakeStore:
    def __init__(self) -> None:
        self.messages = []
        self.deleted = []

    async def upsert_message(self, message) -> None:
        self.messages.append(message)

    async def mark_deleted(self, chat_id: int, message_id: int) -> None:
        self.deleted.append((chat_id, message_id))


class FakeEvents:
    def __init__(self) -> None:
        self.packets = []

    async def publish(self, packet: dict) -> None:
        self.packets.append(packet)


def build_service(client: FakeClient) -> TelegramDesktopService:
    service = object.__new__(TelegramDesktopService)
    service.client = client
    service.status = ClientStatus(
        configured=True,
        connected=True,
        authorized=True,
        state="CONNECTED",
    )
    service.store = FakeStore()
    service.events = FakeEvents()
    return service


@pytest.mark.asyncio
async def test_send_text_keeps_reply_target():
    client = FakeClient()
    service = build_service(client)

    message = await service.send_text(7, "reply", reply_to_message_id=3)

    assert client.sent == [(7, "reply", 3)]
    assert message.reply_to_message_id == 3
    assert service.events.packets[0]["type"] == "MESSAGE_NEW"


@pytest.mark.asyncio
async def test_edit_own_message_updates_store_and_event():
    client = FakeClient(FakeMessage(11, "old", outgoing=True))
    service = build_service(client)

    message = await service.edit_text(7, 11, "new")

    assert client.edited == [(7, 11, "new")]
    assert message.text == "new"
    assert message.edited is True
    assert service.store.messages[-1].message_id == 11
    assert service.events.packets[-1]["type"] == "MESSAGE_EDITED"


@pytest.mark.asyncio
async def test_incoming_message_cannot_be_changed():
    client = FakeClient(FakeMessage(11, "incoming", outgoing=False))
    service = build_service(client)

    with pytest.raises(DesktopError, match="own messages"):
        await service.edit_text(7, 11, "blocked")

    with pytest.raises(DesktopError, match="own messages"):
        await service.delete_message(7, 11)


@pytest.mark.asyncio
async def test_delete_own_message_marks_local_store_and_event():
    client = FakeClient(FakeMessage(11, "mine", outgoing=True))
    service = build_service(client)

    result = await service.delete_message(7, 11)

    assert client.deleted == [(7, [11], True)]
    assert service.store.deleted == [(7, 11)]
    assert service.events.packets[-1] == {
        "type": "MESSAGE_DELETED",
        "data": {"chat_id": 7, "message_id": 11},
    }
    assert result["deleted"] is True
