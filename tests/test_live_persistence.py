import asyncio
from contextlib import suppress

import pytest

from app.models import Message
from app.telegram.service import TelegramDesktopService


class RecordingStore:
    def __init__(self) -> None:
        self.batches: list[list[Message]] = []

    async def upsert_messages(self, messages: list[Message]) -> None:
        self.batches.append(list(messages))


def make_message(message_id: int) -> Message:
    from datetime import datetime, timezone

    return Message(
        chat_id=1,
        message_id=message_id,
        text=str(message_id),
        date=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_live_persistence_worker_batches_messages():
    service = TelegramDesktopService.__new__(TelegramDesktopService)
    service.store = RecordingStore()
    service._message_persist_queue = asyncio.Queue(maxsize=5000)

    worker = asyncio.create_task(service._message_persist_loop())
    try:
        for message_id in range(10):
            service._persist_message_background(make_message(message_id))
        await asyncio.wait_for(service._message_persist_queue.join(), timeout=1.0)

        assert len(service.store.batches) == 1
        assert [item.message_id for item in service.store.batches[0]] == list(range(10))
    finally:
        worker.cancel()
        with suppress(asyncio.CancelledError):
            await worker


@pytest.mark.asyncio
async def test_flush_waits_until_live_persistence_queue_is_drained():
    service = TelegramDesktopService.__new__(TelegramDesktopService)
    service.store = RecordingStore()
    service._message_persist_queue = asyncio.Queue(maxsize=5000)
    service._message_persist_worker = asyncio.create_task(service._message_persist_loop())

    try:
        for message_id in range(3):
            service._persist_message_background(make_message(message_id))
        await service._flush_message_persistence()

        assert service._message_persist_queue.empty()
        assert sum(len(batch) for batch in service.store.batches) == 3
    finally:
        service._message_persist_worker.cancel()
        with suppress(asyncio.CancelledError):
            await service._message_persist_worker
