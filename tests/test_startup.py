import asyncio

from fastapi.testclient import TestClient

import app.main as main
from app.config import Settings


def test_api_answers_while_telegram_is_still_connecting(tmp_path, monkeypatch):
    started = []

    async def slow_start(self):
        started.append(True)
        await asyncio.sleep(30)

    # Never touch a real portable bundle or Telegram from a unit test.
    monkeypatch.setattr(main, "apply_portable_config", lambda settings: None)
    monkeypatch.setattr(main.TelegramDesktopService, "start", slow_start)
    settings = Settings(
        TELEGRAM_CLIENT_DATA_ROOT=str(tmp_path),
        TELEGRAM_API_ID=1,
        TELEGRAM_API_HASH="0123456789abcdef0123",
        TELEGRAM_PROXY_CONFIG=str(tmp_path / "proxies.json"),
        TELEGRAM_DESKTOP_TOKEN="secret",
    )

    with TestClient(main.create_app(settings)) as client:
        health = client.get("/health")
        status = client.get("/api/telegram/status", headers={"X-Desktop-Token": "secret"})
        cached = client.get("/api/cache/dialogs", headers={"X-Desktop-Token": "secret"})
        rejected = client.get("/api/telegram/status")

    assert started == [True]
    assert health.status_code == 200
    assert status.status_code == 200
    assert status.json()["configured"] is True
    assert cached.json() == []
    assert rejected.status_code == 401
