from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.config import Settings
from app.telegram.relay import RelayService, RelayStore


@pytest.mark.asyncio
async def test_relay_source_list_includes_groups_and_supergroups(tmp_path):
    settings = Settings(
        TELEGRAM_API_ID=12345,
        TELEGRAM_API_HASH="test-only-hash",
        TELEGRAM_CLIENT_DATA_ROOT=str(tmp_path / "data"),
        TELEGRAM_PROXY_CONFIG=str(tmp_path / "none.json"),
    )
    dialogs = [
        SimpleNamespace(chat_id=-1, title="Channel", dialog_type="channel"),
        SimpleNamespace(chat_id=-2, title="Group", dialog_type="group"),
        SimpleNamespace(chat_id=-1003, title="Supergroup", dialog_type="supergroup"),
        SimpleNamespace(chat_id=4, title="Private chat", dialog_type="user"),
    ]
    primary = SimpleNamespace(list_dialogs=AsyncMock(return_value=dialogs))
    relay = RelayService(settings, primary, SimpleNamespace())
    await relay.store.initialize()
    assert [item["chat_id"] for item in await relay.source_channels()] == [-1, -2, -1003]
    relay.destination_channels = AsyncMock(return_value=[{"chat_id": -1009, "title": "Destination"}])
    mapping = await relay.add_mapping(-1003, -1009)
    assert mapping["source_title"] == "Supergroup"
    assert -1003 in relay._source_ids


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
async def test_relay_deletes_only_the_destination_message_recorded_for_source(tmp_path):
    settings = Settings(
        TELEGRAM_API_ID=12345,
        TELEGRAM_API_HASH="test-only-hash",
        TELEGRAM_CLIENT_DATA_ROOT=str(tmp_path / "data"),
        TELEGRAM_PROXY_CONFIG=str(tmp_path / "none.json"),
    )
    primary = SimpleNamespace(status=SimpleNamespace(user_id=1))
    relay = RelayService(settings, primary, SimpleNamespace())
    await relay.store.initialize()
    mapping = await relay.store.add_mapping(-1001, -1002, "Source", "Destination")
    await relay.store.enqueue(-1001, 7)
    await relay.store.finish(mapping["id"], 7, "sent", destination_message_id=91)
    assert await relay.store.mark_source_deleted(-1001, 7) == 1
    item = await relay.store.next_delete_pending()
    assert item["destination_chat_id"] == -1002
    assert item["destination_message_id"] == 91
    destination = SimpleNamespace(delete_messages=AsyncMock(), is_connected=lambda: True)
    relay.client = destination
    relay.authorized = True
    await relay._delete_destination(item)
    destination.delete_messages.assert_awaited_once_with(-1002, [91], revoke=True)
    assert (await relay.store.counts()) == {"deleted": 1}
    assert await relay.store.enqueue(-1001, 7) == 0


@pytest.mark.asyncio
async def test_relay_deletion_during_send_is_queued_after_destination_id_is_known(tmp_path):
    store = RelayStore(tmp_path / "relay.sqlite3")
    await store.initialize()
    mapping = await store.add_mapping(-1001, -1002, "Source", "Destination")
    await store.enqueue(-1001, 7)
    await store.mark_source_deleted(-1001, 7)
    assert await store.next_pending() is None
    assert await store.finish(mapping["id"], 7, "sent", destination_message_id=91)
    assert (await store.next_delete_pending())["destination_message_id"] == 91


@pytest.mark.asyncio
async def test_relay_new_event_uses_message_without_network_refetch(tmp_path):
    settings = Settings(
        TELEGRAM_API_ID=12345,
        TELEGRAM_API_HASH="test-only-hash",
        TELEGRAM_CLIENT_DATA_ROOT=str(tmp_path / "data"),
        TELEGRAM_PROXY_CONFIG=str(tmp_path / "none.json"),
    )
    source = SimpleNamespace(get_messages=AsyncMock())
    primary = SimpleNamespace(status=SimpleNamespace(user_id=1), _require_authorized=lambda: source)
    relay = RelayService(settings, primary, SimpleNamespace())
    await relay.store.initialize()
    await relay.store.add_mapping(-1001, -1002, "Source", "Destination")
    relay._source_ids.add(-1001)
    message = SimpleNamespace(raw_text="Fast update", noforwards=False, media=None, chat=None)
    await relay.enqueue(-1001, 7, message)
    destination = SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(id=91)), is_connected=lambda: True)
    relay.client = destination
    relay.authorized = True
    await relay._deliver(await relay.store.next_pending())
    source.get_messages.assert_not_awaited()
    destination.send_message.assert_awaited_once_with(-1002, "Fast update")
    assert relay.last_delivery_ms is not None


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
