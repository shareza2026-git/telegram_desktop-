import asyncio
from contextlib import suppress
from types import SimpleNamespace

import pytest

from app.models import ClientStatus
from app.telegram.service import TelegramDesktopService


class DummySessions:
    def ensure_client_path(self):
        return None

    def info(self):
        return SimpleNamespace(source_available=False, client_exists=False)


@pytest.mark.asyncio
async def test_start_restarts_completed_background_tasks():
    service = TelegramDesktopService.__new__(TelegramDesktopService)
    service._message_persist_worker = asyncio.create_task(asyncio.sleep(0))
    service._connection_monitor = asyncio.create_task(asyncio.sleep(0))
    await asyncio.gather(service._message_persist_worker, service._connection_monitor)

    started = {"persist": 0, "monitor": 0}

    async def persist_loop():
        started["persist"] += 1
        await asyncio.Event().wait()

    async def monitor_loop():
        started["monitor"] += 1
        await asyncio.Event().wait()

    service._message_persist_loop = persist_loop
    service._monitor_connection = monitor_loop
    service.sessions = DummySessions()
    service.settings = SimpleNamespace(
        telegram_configured=False,
        telegram_auto_import_source=False,
    )
    service.status = ClientStatus(configured=False, state="UNCONFIGURED")

    await service.start()

    assert started == {"persist": 1, "monitor": 1}

    service._message_persist_worker.cancel()
    service._connection_monitor.cancel()
    with suppress(asyncio.CancelledError):
        await service._message_persist_worker
    with suppress(asyncio.CancelledError):
        await service._connection_monitor


@pytest.mark.asyncio
async def test_close_cancels_inflight_scan_and_download_tasks():
    service = TelegramDesktopService.__new__(TelegramDesktopService)
    service._connection_monitor = None
    service._message_persist_worker = None
    service._message_persist_queue = asyncio.Queue()
    service._dialog_scan_task = asyncio.create_task(asyncio.Event().wait())
    service._chat_photo_tasks = {7: asyncio.create_task(asyncio.Event().wait())}
    service._media_download_tasks = {(7, 1): asyncio.create_task(asyncio.Event().wait())}
    service.handlers = []
    service.client = None
    service.route = None
    service._dialog_snapshot = []
    service._dialog_snapshot_at = 0.0
    service._chat_info_cache = {}
    service._pinned_cache = {}
    service._typing_state = {}
    service._read_ack_at = {}
    service.status = ClientStatus(configured=True, state="CONNECTED")

    await service.close()

    assert service._dialog_scan_task is None
    assert service._chat_photo_tasks == {}
    assert service._media_download_tasks == {}
    assert service.status.state == "STOPPED"
