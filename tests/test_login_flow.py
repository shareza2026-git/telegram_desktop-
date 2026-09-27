from types import SimpleNamespace

import pytest

from app.models import ClientStatus
from app.telegram.service import TelegramDesktopService


class SignedInClient:
    session = object()

    def __init__(self):
        self.sign_in_calls = []

    async def sign_in(self, **kwargs):
        self.sign_in_calls.append(kwargs)
        return SimpleNamespace(id=123, first_name="User", last_name="Test", phone=None)

    async def get_me(self):
        raise AssertionError("Login must use the user returned by sign_in")


class AuthorizedAfterLostResponseClient(SignedInClient):
    async def sign_in(self, **kwargs):
        self.sign_in_calls.append(kwargs)
        raise TimeoutError

    async def is_user_authorized(self):
        return True

    async def get_me(self):
        return SimpleNamespace(id=456, first_name="Recovered", last_name="User", phone=None)


@pytest.mark.asyncio
@pytest.mark.parametrize("method,credential", [("verify_code", "12345"), ("verify_password", "password")])
async def test_login_does_not_wait_for_another_get_me(monkeypatch, method, credential):
    client = SignedInClient()
    service = TelegramDesktopService.__new__(TelegramDesktopService)
    service.client = client
    service.route = None
    service.login_phone = "+10000000000"
    service.login_code_hash = "challenge"
    service.status = ClientStatus(configured=True, connected=True, state="AUTH_REQUIRED")
    service._register_handlers = lambda: None
    service.settings = object()
    service.transfer_bundle = SimpleNamespace(sync=lambda **kwargs: None)
    monkeypatch.setattr("app.telegram.service.sync_account_to_portable", lambda *args, **kwargs: None)

    result = await getattr(service, method)(credential)

    assert result["authorized"] is True
    assert service.status.state == "CONNECTED"
    assert service.login_phone is None and service.login_code_hash is None
    assert len(client.sign_in_calls) == 1


@pytest.mark.asyncio
async def test_login_recovers_when_telegram_authorized_before_response_was_lost(monkeypatch):
    client = AuthorizedAfterLostResponseClient()
    service = TelegramDesktopService.__new__(TelegramDesktopService)
    service.client = client
    service.route = None
    service.login_phone = "+10000000000"
    service.login_code_hash = "challenge"
    service.status = ClientStatus(configured=True, connected=True, state="AUTH_REQUIRED")
    service._register_handlers = lambda: None
    service.settings = object()
    service.transfer_bundle = SimpleNamespace(sync=lambda **kwargs: None)
    monkeypatch.setattr("app.telegram.service.sync_account_to_portable", lambda *args, **kwargs: None)

    result = await service.verify_code("12345")

    assert result["authorized"] is True
    assert service.status.state == "CONNECTED"
    assert service.status.user_id == 456
    assert service.login_phone is None and service.login_code_hash is None
