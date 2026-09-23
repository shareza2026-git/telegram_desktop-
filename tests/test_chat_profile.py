from pathlib import Path
from types import SimpleNamespace

import pytest

from app.models import ClientStatus
from app.telegram.profile import chat_photo_path, is_fresh_chat_photo
from app.telegram.service import TelegramDesktopService


class UserStatusOnline:
    pass


class FakeEntity:
    first_name = "Test"
    last_name = "User"
    username = "test_user"
    participants_count = None
    status = UserStatusOnline()
    bot = False
    verified = True
    scam = False
    fake = False
    photo = object()


class FakeClient:
    def __init__(self) -> None:
        self.entity = FakeEntity()
        self.photo_downloads = 0

    async def get_entity(self, chat_id: int):
        return self.entity

    async def download_profile_photo(self, entity, file: str):
        self.photo_downloads += 1
        Path(file).write_bytes(b"jpeg")
        return file


def build_service(tmp_path, client: FakeClient) -> TelegramDesktopService:
    service = object.__new__(TelegramDesktopService)
    service.client = client
    service.status = ClientStatus(
        configured=True,
        connected=True,
        authorized=True,
        state="CONNECTED",
    )
    service.settings = SimpleNamespace(project_root=tmp_path)
    return service


@pytest.mark.asyncio
async def test_chat_info_maps_safe_entity_fields(tmp_path):
    service = build_service(tmp_path, FakeClient())

    info = await service.chat_info(7)

    assert info.chat_id == 7
    assert info.title == "Test User"
    assert info.dialog_type == "user"
    assert info.username == "test_user"
    assert info.status == "online"
    assert info.verified is True
    assert info.photo_available is True


@pytest.mark.asyncio
async def test_chat_photo_is_cached_inside_client_data(tmp_path):
    client = FakeClient()
    service = build_service(tmp_path, client)

    first = await service.download_chat_photo(7)
    second = await service.download_chat_photo(7)

    expected = tmp_path / "data" / "telegram_desktop" / "avatars" / "7.jpg"
    assert first.path == expected
    assert second.path == expected
    assert expected.read_bytes() == b"jpeg"
    assert client.photo_downloads == 1


def test_chat_photo_helpers_reject_missing_or_empty_cache(tmp_path):
    target = chat_photo_path(tmp_path, -100)
    assert target == tmp_path / "-100.jpg"
    assert is_fresh_chat_photo(target, now=100) is False

    target.write_bytes(b"")
    assert is_fresh_chat_photo(target, now=100) is False
