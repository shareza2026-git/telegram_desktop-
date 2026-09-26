import asyncio
from datetime import datetime, timezone

import pytest

from app.models import Dialog
from app.telegram.service import TelegramDesktopService


@pytest.mark.asyncio
async def test_dialog_scan_is_coalesced_for_concurrent_requests():
    service = TelegramDesktopService.__new__(TelegramDesktopService)
    service._dialog_snapshot = []
    service._dialog_snapshot_at = 0.0
    service._dialog_scan_task = None
    service._require_authorized = lambda: object()

    calls = 0

    async def scan():
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return [
            Dialog(
                chat_id=1,
                title="One",
                dialog_type="channel",
                unread_count=0,
                pinned=False,
                archived=False,
                muted=False,
                last_message_at=datetime.now(timezone.utc),
            )
        ]

    service._scan_dialogs = scan

    first, second = await asyncio.gather(
        service.list_dialogs(),
        service.list_dialogs(),
    )

    assert calls == 1
    assert first[0].chat_id == 1
    assert second[0].chat_id == 1


@pytest.mark.asyncio
async def test_force_dialog_refresh_bypasses_fresh_cache():
    service = TelegramDesktopService.__new__(TelegramDesktopService)
    service._dialog_snapshot = [
        Dialog(
            chat_id=1,
            title="Cached",
            dialog_type="channel",
            unread_count=0,
            pinned=False,
            archived=False,
            muted=False,
            last_message_at=datetime.now(timezone.utc),
        )
    ]
    service._dialog_snapshot_at = asyncio.get_running_loop().time()
    service._dialog_scan_task = None
    service._require_authorized = lambda: object()

    calls = 0

    async def scan():
        nonlocal calls
        calls += 1
        return [
            Dialog(
                chat_id=2,
                title="Fresh",
                dialog_type="channel",
                unread_count=0,
                pinned=False,
                archived=False,
                muted=False,
                last_message_at=datetime.now(timezone.utc),
            )
        ]

    service._scan_dialogs = scan

    cached = await service.list_dialogs()
    forced = await service.list_dialogs(force=True)

    assert cached[0].chat_id == 1
    assert forced[0].chat_id == 2
    assert calls == 1
