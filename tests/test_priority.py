import asyncio

import pytest

from app.telegram.priority import PriorityChats
from app.telegram.service import EventBroker


def test_quote_rooms_are_priority_by_title(tmp_path):
    rules = PriorityChats(tmp_path / "priority_chats.json")

    assert rules.is_priority(1, "اتاق آبشده فرزاد") is True
    assert rules.is_priority(2, "قیمت لحظه ای سکه") is True
    assert rules.is_priority(3, "Family") is False


def test_manual_choice_overrides_keywords_and_survives_restart(tmp_path):
    path = tmp_path / "priority_chats.json"
    rules = PriorityChats(path)
    rules.set(1, "اتاق آبشده", False)
    rules.set(3, "Family", True)

    reloaded = PriorityChats(path)

    assert reloaded.is_priority(1, "اتاق آبشده") is False
    assert reloaded.is_priority(3, "Family") is True


def test_turning_back_to_the_keyword_default_stores_nothing(tmp_path):
    path = tmp_path / "priority_chats.json"
    rules = PriorityChats(path)
    rules.set(1, "اتاق", False)
    rules.set(1, "اتاق", True)

    assert PriorityChats(path).is_priority(1, "اتاق") is True
    assert '"off": []' in path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_priority_packets_overtake_a_backlog():
    broker = EventBroker()
    queue = broker.subscribe()
    for index in range(50):
        await broker.publish({"type": "MESSAGE_NEW", "data": {"chat_id": 1, "message_id": index}})

    await broker.publish({"type": "MESSAGE_NEW", "data": {"chat_id": 2, "message_id": 999}, "priority": True})

    first = await asyncio.wait_for(queue.get(), timeout=0.1)
    second = await asyncio.wait_for(queue.get(), timeout=0.1)
    assert first["data"]["message_id"] == 999
    assert second["data"]["message_id"] == 0


@pytest.mark.asyncio
async def test_subscriber_waits_for_the_next_packet():
    broker = EventBroker()
    queue = broker.subscribe()

    waiter = asyncio.create_task(queue.get())
    await asyncio.sleep(0)
    await broker.publish({"type": "READY", "data": {}})

    assert (await asyncio.wait_for(waiter, timeout=0.1))["type"] == "READY"
    assert queue.empty()
