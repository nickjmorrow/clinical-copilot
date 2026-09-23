"""The live fan-out, on its own — `app/bus.py`.

`publish` is reached from several places (`worker/turn.py`, `worker/handlers.py`,
`services/task_service.py`) and none of them should have to know Postgres caps
a NOTIFY payload at 8000 bytes. This file is the one place that guarantee is
pinned directly against the function, rather than only indirectly through
whichever caller happens to publish something large this month.
"""

import asyncio

import pytest

from app.bus import MAX_NOTIFY_PAYLOAD_BYTES, Bus, channel_for, publish
from app.services import conversation_service


@pytest.fixture
async def bus():
    instance = Bus()
    await instance.start()
    try:
        yield instance
    finally:
        await instance.stop()


async def test_a_small_frame_is_published_and_received(session, bus):
    conversation = await conversation_service.create_conversation(session, user_id="dev-user")
    channel = channel_for(conversation.id)

    async with bus.subscribe(channel) as queue:
        await publish(session, channel, {"type": "text", "text": "hi"})
        frame = await asyncio.wait_for(queue.get(), timeout=2)

    assert frame == {"type": "text", "text": "hi"}


async def test_an_oversized_frame_is_dropped_not_raised(session, bus, caplog):
    """The regression case: a `tool_result` for a real cohort serializes well
    past 8000 bytes, and `select pg_notify(...)` used to raise
    `InvalidParameterValueError` straight out of `publish`, which crashed the
    worker mid-turn. A frame this large must never reach Postgres, and must
    never raise."""
    conversation = await conversation_service.create_conversation(session, user_id="dev-user")
    channel = channel_for(conversation.id)
    oversized = {"type": "event", "event": {"content": "x" * (MAX_NOTIFY_PAYLOAD_BYTES + 500)}}

    async with bus.subscribe(channel) as queue:
        await publish(session, channel, oversized)  # must not raise
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(queue.get(), timeout=0.2)


async def test_a_frame_right_at_the_boundary_still_publishes(session, bus):
    """Not just "big things are dropped" — the cutoff itself has to be in the
    right place, one byte on the safe side of Postgres's actual limit."""
    conversation = await conversation_service.create_conversation(session, user_id="dev-user")
    channel = channel_for(conversation.id)
    # Overhead of the envelope itself (`{"type": "text", "text": "..."}`) eats
    # a couple dozen bytes of the budget.
    padding = "x" * (MAX_NOTIFY_PAYLOAD_BYTES - 100)
    frame = {"type": "text", "text": padding}

    async with bus.subscribe(channel) as queue:
        await publish(session, channel, frame)
        received = await asyncio.wait_for(queue.get(), timeout=2)

    assert received == frame
