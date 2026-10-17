from types import SimpleNamespace

import pytest
from telethon import types

from app.models import ClientStatus
from app.telegram.service import TelegramDesktopService


class FakeStore:
    def __init__(self) -> None:
        self.dialogs = []

    async def upsert_dialog(self, dialog) -> None:
        self.dialogs.append(dialog)


class FakeClient:
    def __init__(self) -> None:
        self.requests = []

    async def __call__(self, request):
        self.requests.append(request)
        name = type(request).__name__
        if name == "GetContactsRequest":
            return SimpleNamespace(
                users=[
                    SimpleNamespace(id=2, first_name="Zahra", last_name=None, username="z", phone="98912", status=None, deleted=False),
                    SimpleNamespace(id=1, first_name="Ali", last_name="R", username=None, phone=None, status=None, deleted=False),
                    SimpleNamespace(id=3, first_name="Gone", last_name=None, username=None, phone=None, status=None, deleted=True),
                ]
            )
        if name == "CreateChannelRequest":
            return SimpleNamespace(chats=[types.Channel(
                id=555, title=request.title, photo=types.ChatPhotoEmpty(), date=None,
                megagroup=request.megagroup, broadcast=request.broadcast, access_hash=1,
            )])
        raise AssertionError(name)


def build_service() -> TelegramDesktopService:
    service = object.__new__(TelegramDesktopService)
    service.client = FakeClient()
    service.status = ClientStatus(configured=True, connected=True, authorized=True, state="CONNECTED")
    service.store = FakeStore()
    service._dialog_snapshot = []
    return service


@pytest.mark.asyncio
async def test_contacts_are_sorted_and_skip_deleted_accounts():
    service = build_service()

    values = await service.contacts()

    assert [item.title for item in values] == ["Ali R", "Zahra"]
    assert values[1].username == "z"


@pytest.mark.asyncio
async def test_new_group_is_a_supergroup_and_appears_first():
    service = build_service()

    dialog = await service.create_chat("  تیم معاملات ", "group")

    request = service.client.requests[-1]
    assert request.megagroup is True and request.broadcast is False
    assert request.title == "تیم معاملات"
    assert dialog.dialog_type == "supergroup"
    assert dialog.chat_id == -1000000000555
    assert service._dialog_snapshot[0] is dialog
    assert service.store.dialogs == [dialog]


@pytest.mark.asyncio
async def test_new_channel_is_a_broadcast():
    service = build_service()

    dialog = await service.create_chat("اخبار", "channel", "قیمت لحظه‌ای")

    request = service.client.requests[-1]
    assert request.broadcast is True and request.megagroup is False
    assert request.about == "قیمت لحظه‌ای"
    assert dialog.dialog_type == "channel"
