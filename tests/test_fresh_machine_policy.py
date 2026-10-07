import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.models import ApiConfigRequest, ClientStatus
from app.telegram.client import device_model
from app.telegram.portable import _candidate_paths
from app.telegram.service import TelegramDesktopService
from app.telegram.transport import TransportCatalog


def test_device_model_prefers_real_windows_computer_name(monkeypatch):
    monkeypatch.setenv("COMPUTERNAME", "NEW-WINDOWS-PC")
    monkeypatch.setattr("platform.node", lambda: "fallback-node")

    assert device_model() == "NEW-WINDOWS-PC"


def test_portable_config_has_no_implicit_executable_discovery(monkeypatch):
    monkeypatch.delenv("TELEGRAM_PORTABLE_CONFIG", raising=False)

    assert _candidate_paths(SimpleNamespace()) == []


def test_portable_config_requires_explicit_path(monkeypatch, tmp_path: Path):
    target = tmp_path / "telegram-portable.json"
    monkeypatch.setenv("TELEGRAM_PORTABLE_CONFIG", str(target))

    assert _candidate_paths(SimpleNamespace()) == [target.resolve()]


def test_transport_catalog_uses_explicit_xray_core(tmp_path: Path):
    xray = tmp_path / "tools" / "xray.exe"
    catalog = TransportCatalog(
        tmp_path / "proxies.json",
        xray_core_path=xray,
    )

    assert catalog._xray_core_path() == xray.resolve()


def test_direct_selection_is_ignored_when_direct_policy_is_disabled():
    service = TelegramDesktopService.__new__(TelegramDesktopService)
    service.settings = SimpleNamespace(telegram_allow_direct=False)
    routes = [object(), object()]

    assert service._connection_candidates(routes, 0) == routes
    assert service._connection_candidates(routes, None) == routes


def test_direct_selection_is_available_only_after_explicit_opt_in():
    service = TelegramDesktopService.__new__(TelegramDesktopService)
    service.settings = SimpleNamespace(telegram_allow_direct=True)
    routes = [object()]

    assert service._connection_candidates(routes, 0) == [None, routes[0]]


class DummyTransport:
    def load(self):
        return []


class DummySessions:
    def info(self):
        return SimpleNamespace(client_exists=False)


class DummyTransfer:
    def __init__(self):
        self.calls = []

    def sync(self, *, include_session=True):
        self.calls.append(include_session)


class DummyEvents:
    async def publish(self, packet):
        return None


@pytest.mark.asyncio
async def test_saving_api_credentials_does_not_enable_direct_connectivity(tmp_path: Path):
    service = TelegramDesktopService.__new__(TelegramDesktopService)
    service.settings = SimpleNamespace(
        data_root=tmp_path,
        telegram_allow_direct=False,
        telegram_api_id=None,
        telegram_api_hash=None,
    )
    service.transport = DummyTransport()
    service.sessions = DummySessions()
    service.transfer_bundle = DummyTransfer()
    service.events = DummyEvents()
    service._lifecycle_lock = asyncio.Lock()
    service.handlers = []
    service.client = None
    service.route = None
    service.status = ClientStatus(
        configured=False,
        connected=False,
        authorized=False,
        state="UNCONFIGURED",
    )
    service._reset_connection_caches = lambda: None

    async def fake_connect():
        service.status = service.status.model_copy(
            update={"state": "PROXY_ERROR", "connected": False}
        )

    service._connect = fake_connect

    await service.set_runtime_config(
        ApiConfigRequest(api_id=12345, api_hash="0123456789abcdef0123456789abcdef")
    )

    assert service.settings.telegram_allow_direct is False
    settings_text = (tmp_path / "settings.env").read_text(encoding="utf-8")
    assert "TELEGRAM_ALLOW_DIRECT=false" in settings_text


@pytest.mark.asyncio
async def test_select_proxy_rejects_direct_when_policy_is_disabled():
    service = TelegramDesktopService.__new__(TelegramDesktopService)
    service.settings = SimpleNamespace(telegram_allow_direct=False)
    service.transport = DummyTransport()

    with pytest.raises(ValueError, match="Direct Telegram connection is disabled"):
        await service.select_proxy(0)
