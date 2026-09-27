from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.config import Settings
from app.telegram.relay import RelayService, RelayStore


@pytest.mark.asyncio
async def test_relay_store_keeps_distinct_mappings_and_deduplicates_events(tmp_path):
    store = RelayStore(tmp_path / "relay.sqlite3")
    await store.initialize()
    first = await store.add_mapping(-1001, -1002, "Source", "Destination")
    assert await store.add_mapping(-1001, -1002, "Source", "Destination") == first
    second = await store.add_mapping(-1001, -1003, "Source", "Other")
    assert second["id"] != first["id"]
    assert await store.enqueue(-1001, 42) == 2
    assert await store.enqueue(-1001, 42) == 0
    assert (await store.counts())["pending"] == 2
    await store.finish(first["id"], 42, "sent", destination_message_id=99)
    assert (await store.counts()) == {"pending": 1, "sent": 1}
    assert await store.remove_mapping(second["id"])
    assert (await store.counts()) == {"sent": 1}


@pytest.mark.asyncio
async def test_relay_sends_new_text_from_primary_via_second_account(tmp_path):
    settings = Settings(
        TELEGRAM_API_ID=12345,
        TELEGRAM_API_HASH="test-only-hash",
        TELEGRAM_CLIENT_DATA_ROOT=str(tmp_path / "data"),
        TELEGRAM_PROXY_CONFIG=str(tmp_path / "none.json"),
    )
    message = SimpleNamespace(raw_text="Market update", noforwards=False, media=None, chat=None)
    source = SimpleNamespace(get_messages=AsyncMock(return_value=message))
    primary = SimpleNamespace(status=SimpleNamespace(user_id=1), _require_authorized=lambda: source)
    relay = RelayService(settings, primary, SimpleNamespace())
    await relay.store.initialize()
    mapping = await relay.store.add_mapping(-1001, -1002, "Source", "Destination")
    await relay.store.enqueue(-1001, 7)
    destination = SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(id=91)), is_connected=lambda: True)
    relay.client = destination
    relay.authorized = True
    await relay._deliver({"mapping_id": mapping["id"], "source_message_id": 7, "source_chat_id": -1001, "destination_chat_id": -1002})
    source.get_messages.assert_awaited_once_with(-1001, ids=7)
    destination.send_message.assert_awaited_once_with(-1002, "Market update")
    assert (await relay.store.counts())["sent"] == 1


@pytest.mark.asyncio
async def test_relay_does_not_copy_protected_content(tmp_path):
    settings = Settings(
        TELEGRAM_API_ID=12345,
        TELEGRAM_API_HASH="test-only-hash",
        TELEGRAM_CLIENT_DATA_ROOT=str(tmp_path / "data"),
        TELEGRAM_PROXY_CONFIG=str(tmp_path / "none.json"),
    )
    message = SimpleNamespace(raw_text="Private", noforwards=True, media=None, chat=None)
    source = SimpleNamespace(get_messages=AsyncMock(return_value=message))
    primary = SimpleNamespace(status=SimpleNamespace(user_id=1), _require_authorized=lambda: source)
    relay = RelayService(settings, primary, SimpleNamespace())
    await relay.store.initialize()
    mapping = await relay.store.add_mapping(-1001, -1002, "Source", "Destination")
    await relay.store.enqueue(-1001, 7)
    destination = SimpleNamespace(send_message=AsyncMock(), is_connected=lambda: True)
    relay.client = destination
    relay.authorized = True
    await relay._deliver({"mapping_id": mapping["id"], "source_message_id": 7, "source_chat_id": -1001, "destination_chat_id": -1002})
    destination.send_message.assert_not_awaited()
    assert (await relay.store.counts())["blocked"] == 1
