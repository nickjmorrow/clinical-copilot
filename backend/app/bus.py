"""Live fan-out from the worker to whoever is watching.

The worker and the API are separate processes, so the worker cannot hand a
token to an open HTTP response — there is no shared memory to hand it through.
Postgres already sits between them, and it has `LISTEN`/`NOTIFY`, so that is the
channel. No Redis, no message broker.

**Two channels, on purpose.** Durable state goes in `event_records`, which can
be replayed from any point by `seq`. Tokens go through here, and are gone if
nobody was listening. That split is the whole design: a token is not worth a row
and a row is not fast enough for a token, and because every durable event is
*also* published here, a dropped token self-heals — the authoritative text
arrives moments later as an `assistant_message` event and replaces the preview.

NOTIFY payloads are capped at 8000 bytes by Postgres. Deltas and event frames
are far below that; if you ever publish something large, publish a pointer to a
row instead.
"""

import asyncio
import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

import asyncpg
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.logging import get_logger

logger = get_logger(__name__)

# Bounded so one stalled browser cannot grow a queue without limit. Overflow
# drops the oldest frames, which costs a flicker of live text and nothing more —
# the durable events behind it are still in the database.
SUBSCRIBER_QUEUE_SIZE = 512

# Postgres hard-caps a NOTIFY payload at 8000 bytes and raises if it is
# exceeded. Headroom below that is for `:channel` and pg_notify's own
# framing, which count against the same limit but are not part of `frame`.
MAX_NOTIFY_PAYLOAD_BYTES = 7800


def channel_for(conversation_id: UUID) -> str:
    """Postgres channel names are identifiers, so no dashes and 63 chars max."""
    return f"conv_{conversation_id.hex}"


class Bus:
    """One LISTEN connection per process, fanned out in memory.

    The naive version opens a Postgres connection per open stream. That works
    until two people leave tabs open. One connection and a dict of subscribers
    costs the same code and does not fall over.
    """

    def __init__(self) -> None:
        self._connection: asyncpg.Connection | None = None
        self._subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = {}

    async def start(self) -> None:
        self._connection = await asyncpg.connect(settings.database_dsn)
        logger.info("bus connected")

    async def stop(self) -> None:
        if self._connection is not None:
            await self._connection.close()
            self._connection = None
            logger.info("bus disconnected")

    def _on_notify(self, _conn: Any, _pid: int, channel: str, payload: str) -> None:
        # Called by asyncpg on the event loop. Must not block and must not
        # raise — an exception here is swallowed by the driver and the
        # subscriber simply never hears anything again.
        try:
            frame = json.loads(payload)
        except json.JSONDecodeError:
            logger.error("bus payload not json", channel=channel)
            return

        for queue in self._subscribers.get(channel, set()):
            try:
                queue.put_nowait(frame)
            except asyncio.QueueFull:
                logger.warning("bus subscriber lagging", channel=channel)

    @asynccontextmanager
    async def subscribe(self, channel: str) -> AsyncGenerator[asyncio.Queue[dict[str, Any]]]:
        """Receive frames published on `channel` for as long as the block runs."""
        if self._connection is None:
            raise RuntimeError("bus not started")

        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=SUBSCRIBER_QUEUE_SIZE)
        listeners = self._subscribers.setdefault(channel, set())

        # Only the first subscriber to a channel talks to Postgres; the rest
        # join the in-memory set.
        if not listeners:
            await self._connection.add_listener(channel, self._on_notify)
        listeners.add(queue)

        try:
            yield queue
        finally:
            listeners.discard(queue)
            if not listeners:
                self._subscribers.pop(channel, None)
                if self._connection is not None:  # pyright: ignore[reportUnnecessaryComparison]
                    await self._connection.remove_listener(channel, self._on_notify)


async def publish(session: AsyncSession, channel: str, frame: dict[str, Any]) -> None:
    """Send one frame to everyone listening on `channel`.

    Publishing goes through the ordinary session rather than the bus's own
    connection: NOTIFY is transactional, so this is delivered when the
    surrounding transaction commits and never announces something a reader
    cannot yet see.

    A frame too large for NOTIFY is dropped rather than sent — never raised.
    Every frame this publishes for a durable event already has a row in
    `event_records` (see the module docstring's "two channels"), so a browser
    that misses this one gets the same content moments later from a fetch or
    a replay. A `find_patients` result for a large cohort is the case this
    exists for: a tool_result event serializes well past 8000 bytes once a
    cohort clears roughly 190 rows, and letting Postgres reject that NOTIFY
    used to crash the worker mid-turn — the fix belongs here, once, rather
    than at every call site that might someday publish something large.
    """
    payload = json.dumps(frame)
    payload_bytes = len(payload.encode())
    if payload_bytes > MAX_NOTIFY_PAYLOAD_BYTES:
        logger.warning(
            "bus payload too large to publish live",
            channel=channel,
            frame_type=frame.get("type"),
            payload_bytes=payload_bytes,
        )
        return

    await session.execute(
        text("select pg_notify(:channel, :payload)"), {"channel": channel, "payload": payload}
    )
    await session.commit()


# One per process. Started and stopped by the app lifespan in main.py, and by
# the worker in worker.py.
bus = Bus()
