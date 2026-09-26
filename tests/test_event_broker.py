import asyncio

import pytest

from app.telegram.service import EventBroker


@pytest.mark.asyncio
async def test_filtered_subscriber_receives_only_matching_chat_packets():
    broker = EventBroker()
    queue = broker.subscribe(chat_id=42)

    await broker.publish({"type": "MESSAGE_NEW", "data": {"chat_id": 7}})
    await broker.publish({"type": "MESSAGE_NEW", "data": {"chat_id": 42}})

    packet = await asyncio.wait_for(queue.get(), timeout=0.1)
    assert packet["data"]["chat_id"] == 42
    assert queue.empty()


@pytest.mark.asyncio
async def test_queue_overflow_resync_keeps_subscriber_registered():
    broker = EventBroker()
    queue = broker.subscribe()

    for index in range(queue.maxsize):
        queue.put_nowait({"type": "MESSAGE_NEW", "data": {"chat_id": 1, "message_id": index}})

    await broker.publish({"type": "MESSAGE_NEW", "data": {"chat_id": 1, "message_id": 9999}})
    assert await asyncio.wait_for(queue.get(), timeout=0.1) == {"type": "RESYNC", "data": {}}

    await broker.publish({"type": "MESSAGE_NEW", "data": {"chat_id": 1, "message_id": 10000}})
    packet = await asyncio.wait_for(queue.get(), timeout=0.1)
    assert packet["data"]["message_id"] == 10000
