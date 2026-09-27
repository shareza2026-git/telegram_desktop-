import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.models import ClientStatus
from app.telegram.service import TelegramDesktopService


@pytest.mark.asyncio
async def test_select_proxy_returns_while_network_connection_is_pending():
    service = TelegramDesktopService.__new__(TelegramDesktopService)
    service.settings = SimpleNamespace(telegram_configured=True)
    service.status = ClientStatus(configured=True, state="AUTH_REQUIRED")
    chosen = []
    service.transport = SimpleNamespace(
        load=lambda: [object()],
        set_selected_index=chosen.append,
    )
    waiting = asyncio.Event()
    service._apply_proxy_selection = AsyncMock(side_effect=waiting.wait)
    service._proxy_switch_task = None
    service._proxy_switch_generation = 0

    result = await asyncio.wait_for(service.select_proxy(1), timeout=0.1)

    assert result["selected_index"] == 1
    assert chosen == [1]
    assert service._proxy_switch_task is not None
    service._proxy_switch_task.cancel()
    await asyncio.gather(service._proxy_switch_task, return_exceptions=True)
