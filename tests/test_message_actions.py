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
        self.reactions = None


class FakeClient:
    def __init__(self, existing: FakeMessage | None = None) -> None:
        self.existing = existing
        self.sent: list[tuple[int, str, int | None]] = []
        self.edited: list[tuple[int, int, str]] = []
        self.deleted: list[tuple[int, list[int], bool]] = []
        self.searched: list[tuple[int, str, int]] = []
        self.forwarded: list[tuple[int, int]] = []
        self.files = []
        self.reaction_requests = []
        self.typing_requests = []
        self.pinned_requests = []

    async def get_messages(
        self,
        chat_id: int,
        ids: int | None = None,
        limit: int | None = None,
        filter=None,
    ):
        if filter is not None:
            self.pinned_requests.append((chat_id, limit, type(filter).__name__))
            return [self.existing] if self.existing is not None else []
        return self.existing

    async def get_input_entity(self, chat_id: int):
        return chat_id

    async def __call__(self, request):
        if hasattr(request, "reaction"):
            self.reaction_requests.append(request)
            emoji = request.reaction[0].emoticon if request.reaction else None
            if self.existing is not None:
                if emoji:
                    reaction = type("Reaction", (), {"emoticon": emoji})()
                    result = type(
                        "ReactionCount",
                        (),
                        {"reaction": reaction, "count": 1, "chosen_order": 0},
                    )()
                    self.existing.reactions = type("Reactions", (), {"results": [result]})()
                else:
                    self.existing.reactions = type("Reactions", (), {"results": []})()
        if hasattr(request, "action"):
            self.typing_requests.append(request)
        return object()

    async def iter_messages(self, chat_id: int, search: str, limit: int):
        self.searched.append((chat_id, search, limit))
        yield FakeMessage(14, "new result", outgoing=False)
        yield FakeMessage(9, "old result", outgoing=False)

    async def send_message(self, chat_id: int, text: str, reply_to: int | None = None):
        self.sent.append((chat_id, text, reply_to))
        return FakeMessage(20, text, reply_to_message_id=reply_to)

    async def forward_messages(self, target_chat_id: int, source: FakeMessage):
        self.forwarded.append((target_chat_id, source.id))
        return FakeMessage(30, source.raw_text, outgoing=True)

    async def send_file(
        self,
        chat_id: int,
        file,
        caption: str | None,
        reply_to: int | None,
    ):
        self.files.append((chat_id, file, caption, reply_to))

        def sent_message(message_id: int, name: str):
            message = FakeMessage(message_id, caption or "", reply_to_message_id=reply_to)
            message.media = object()
            message.document = object()
            message.file = type("File", (), {
                "name": name,
                "size": 4,
                "mime_type": "application/pdf",
            })()
            return message

        if isinstance(file, list):
            return [sent_message(40 + index, str(path).split("/")[-1]) for index, path in enumerate(file)]
        return sent_message(40, str(file).split("/")[-1])

    async def edit_message(self, chat_id: int, message_id: int, text: str):
        self.edited.append((chat_id, message_id, text))
        return FakeMessage(message_id, text)

    async def delete_messages(self, chat_id: int, message_ids: list[int], revoke: bool):
        self.deleted.append((chat_id, message_ids, revoke))


class FakeStore:
    def __init__(self) -> None:
        self.messages = []
        self.deleted = []
        self.read_ranges = []

    async def upsert_message(self, message) -> None:
        self.messages.append(message)

    async def mark_outgoing_read(self, chat_id: int, max_id: int) -> None:
        self.read_ranges.append((chat_id, max_id))

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
    service._outbox_read_max = {}
    service._recent_media = {}
    return service


@pytest.mark.asyncio
async def test_pinned_message_uses_telegram_filter_and_persists():
    client = FakeClient(FakeMessage(15, "pinned", outgoing=False))
    service = build_service(client)

    result = await service.pinned_message(7)

    assert client.pinned_requests == [(7, 1, "InputMessagesFilterPinned")]
    assert result is not None
    assert result.message_id == 15
    assert service.store.messages[-1].message_id == 15


@pytest.mark.asyncio
async def test_pinned_message_returns_none_when_chat_has_no_pin():
    client = FakeClient()
    service = build_service(client)

    result = await service.pinned_message(7)

    assert result is None
    assert service.store.messages == []


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


@pytest.mark.asyncio
async def test_search_messages_uses_telegram_and_persists_results():
    client = FakeClient()
    service = build_service(client)

    results = await service.search_messages(7, "  gold  ", limit=25)

    assert client.searched == [(7, "gold", 25)]
    assert [message.message_id for message in results] == [14, 9]
    assert [message.message_id for message in service.store.messages] == [14, 9]


@pytest.mark.asyncio
async def test_search_messages_rejects_short_query():
    client = FakeClient()
    service = build_service(client)

    with pytest.raises(ValueError, match="at least 2"):
        await service.search_messages(7, " ")


@pytest.mark.asyncio
async def test_forward_message_persists_in_target_chat_and_publishes():
    client = FakeClient(FakeMessage(11, "forward me", outgoing=False))
    service = build_service(client)

    result = await service.forward_message(7, 11, 99)

    assert client.forwarded == [(99, 11)]
    assert result.chat_id == 99
    assert result.message_id == 30
    assert service.store.messages[-1].chat_id == 99
    assert service.events.packets[-1]["type"] == "MESSAGE_NEW"


@pytest.mark.asyncio
async def test_send_file_keeps_caption_reply_and_live_event(tmp_path):
    client = FakeClient()
    service = build_service(client)
    path = tmp_path / "report.pdf"
    path.write_bytes(b"test")

    result = await service.send_file(7, str(path), "caption", reply_to_message_id=3)

    assert client.files == [(7, str(path), "caption", 3)]
    assert result.message_id == 40
    assert result.text == "caption"
    assert result.reply_to_message_id == 3
    assert result.media is not None
    assert service.store.messages[-1].message_id == 40
    assert service.events.packets[-1]["type"] == "MESSAGE_NEW"


@pytest.mark.asyncio
async def test_send_files_persists_and_publishes_every_album_item(tmp_path):
    client = FakeClient()
    service = build_service(client)
    paths = [str(tmp_path / "one.pdf"), str(tmp_path / "two.pdf")]

    results = await service.send_files(7, paths, "album", reply_to_message_id=3)

    assert client.files == [(7, paths, "album", 3)]
    assert [message.message_id for message in results] == [40, 41]
    assert [message.message_id for message in service.store.messages] == [40, 41]
    assert [packet["type"] for packet in service.events.packets] == ["MESSAGE_NEW", "MESSAGE_NEW"]



@pytest.mark.asyncio
async def test_set_and_remove_reaction_updates_store_and_live_event():
    client = FakeClient(FakeMessage(11, "react", outgoing=False))
    service = build_service(client)

    reacted = await service.set_reaction(7, 11, "👍")

    assert client.reaction_requests[-1].msg_id == 11
    assert client.reaction_requests[-1].reaction[0].emoticon == "👍"
    assert reacted.reactions[0].emoji == "👍"
    assert reacted.reactions[0].chosen is True
    assert service.events.packets[-1]["type"] == "MESSAGE_EDITED"

    cleared = await service.set_reaction(7, 11, None)

    assert client.reaction_requests[-1].reaction is None
    assert cleared.reactions == []
    assert service.store.messages[-1].message_id == 11



@pytest.mark.asyncio
async def test_send_typing_and_cancel_use_telegram_actions():
    client = FakeClient()
    service = build_service(client)

    active = await service.send_typing(7, True)
    cancelled = await service.send_typing(7, False)

    assert type(client.typing_requests[0].action).__name__ == "SendMessageTypingAction"
    assert type(client.typing_requests[1].action).__name__ == "SendMessageCancelAction"
    assert active == {"chat_id": 7, "typing": True}
    assert cancelled == {"chat_id": 7, "typing": False}


@pytest.mark.asyncio
async def test_outbox_read_event_marks_store_and_publishes():
    client = FakeClient()
    service = build_service(client)
    event = type(
        "ReadEvent",
        (),
        {"chat_id": 7, "outbox": True, "max_id": 25},
    )()

    await service._on_read(event)

    assert service._outbox_read_max[7] == 25
    assert service.store.read_ranges == [(7, 25)]
    assert service.events.packets[-1] == {
        "type": "MESSAGES_READ",
        "data": {"chat_id": 7, "max_id": 25},
    }
