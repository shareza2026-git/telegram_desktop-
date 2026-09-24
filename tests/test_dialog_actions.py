from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.models import ClientStatus
from app.telegram.service import TelegramDesktopService


class FakeClient:
    def __init__(self) -> None:
        self.requests = []
        self.folder_edits = []

    async def get_input_entity(self, chat_id: int):
        return "peer:" + str(chat_id)

    async def edit_folder(self, chat_id: int, folder: int):
        self.folder_edits.append((chat_id, folder))
        return object()

    async def __call__(self, request):
        self.requests.append(request)
        return object()


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
    service.events = FakeEvents()
    return service


@pytest.mark.asyncio
async def test_dialog_pin_uses_input_dialog_peer_and_publishes():
    client = FakeClient()
    service = build_service(client)

    result = await service.set_dialog_pinned(7, True)

    request = client.requests[-1]
    assert type(request).__name__ == "ToggleDialogPinRequest"
    assert request.pinned is True
    assert request.peer.peer == "peer:7"
    assert result == {"chat_id": 7, "pinned": True}
    assert service.events.packets[-1] == {
        "type": "DIALOG_UPDATED",
        "data": result,
    }


@pytest.mark.asyncio
async def test_dialog_archive_uses_telegram_folder():
    client = FakeClient()
    service = build_service(client)

    archived = await service.set_dialog_archived(7, True)
    restored = await service.set_dialog_archived(7, False)

    assert client.folder_edits == [(7, 1), (7, 0)]
    assert archived == {"chat_id": 7, "archived": True}
    assert restored == {"chat_id": 7, "archived": False}


@pytest.mark.asyncio
async def test_dialog_mute_updates_peer_notification_settings():
    client = FakeClient()
    service = build_service(client)

    muted = await service.set_dialog_muted(7, True)
    mute_request = client.requests[-1]
    unmuted = await service.set_dialog_muted(7, False)
    unmute_request = client.requests[-1]

    assert type(mute_request).__name__ == "UpdateNotifySettingsRequest"
    assert mute_request.peer.peer == "peer:7"
    assert mute_request.settings.mute_until == datetime(2038, 1, 18, tzinfo=timezone.utc)
    assert unmute_request.settings.mute_until <= datetime.now(timezone.utc)
    assert muted == {"chat_id": 7, "muted": True}
    assert unmuted == {"chat_id": 7, "muted": False}


def test_dialog_model_reads_active_mute_state():
    future = datetime(2038, 1, 18, tzinfo=timezone.utc)
    raw = SimpleNamespace(notify_settings=SimpleNamespace(mute_until=future))
    dialog = SimpleNamespace(
        entity=SimpleNamespace(first_name="Test", last_name="User", username=None),
        is_user=True,
        is_channel=False,
        is_group=False,
        id=7,
        title="Test User",
        unread_count=3,
        pinned=False,
        folder_id=None,
        message=None,
        dialog=raw,
    )

    value = TelegramDesktopService._dialog_model(dialog)

    assert value.chat_id == 7
    assert value.muted is True
