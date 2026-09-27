from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.models import ClientStatus
from app.telegram.service import TelegramDesktopService


@pytest.mark.asyncio
async def test_next_launch_tries_successful_fallback_before_failed_proxy(monkeypatch):
    bad = SimpleNamespace(display_name='test-unavailable', activate=AsyncMock(return_value={'route': 1}), deactivate=AsyncMock())
    good = SimpleNamespace(display_name='test-working', activate=AsyncMock(return_value={'route': 2}), deactivate=AsyncMock())
    selected = [1]
    attempts = []

    def build(settings, options, session):
        attempts.append(options['route'])
        return SimpleNamespace(
            connect=AsyncMock(side_effect=OSError('unavailable') if options['route'] == 1 else None),
            is_user_authorized=AsyncMock(return_value=False),
            disconnect=AsyncMock(),
        )

    monkeypatch.setattr('app.telegram.service.build_client', build)
    service = TelegramDesktopService.__new__(TelegramDesktopService)
    service.settings = SimpleNamespace()
    service.status = ClientStatus(configured=True, state='CONNECTING')
    service.sessions = SimpleNamespace(clone_runtime_session=lambda: (None, {}))
    service.transport = SimpleNamespace(
        load=lambda: [bad, good],
        selected_index=lambda: selected[0],
        set_selected_index=lambda value: selected.__setitem__(0, value),
    )
    await service._connect()
    assert service.status.state == 'AUTH_REQUIRED'
    assert selected[0] == 2
    await service.client.disconnect()
    await service._connect()
    assert attempts == [1, 2, 2]
    assert not service.status.authorized
