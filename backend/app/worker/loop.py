"""The process: claim, run, settle, wait for a NOTIFY, repeat.

Run with `python -m app.worker`. The worker is a separate process from the API
on purpose, and that separation is the point rather than an implementation
detail: because the thing doing the work cannot see the thing serving the
request, every interesting problem becomes explicit instead of implicit.
Cancellation has to travel through the database. A dead worker has to be
noticed by someone else. A second message arriving mid-turn has to resolve to a
decision. Put generation back inside the request handler and all three
disappear — along with the guarantee that closing a tab does not cost you the
turn.

The loop is: expand due schedules, sweep dead workers, drain the queue, wait for
a NOTIFY. Nothing clever, and nothing that needs to be.
"""

import asyncio
import os
import secrets
import socket
from functools import lru_cache

from app.bus import bus
from app.config import settings
from app.db import SessionFactory, engine
from app.llm.base import LLMProvider
from app.logging import configure_logging, get_logger
from app.services import task_service
from app.worker import shutdown
from app.worker.handlers import execute

logger = get_logger(__name__)


@lru_cache(maxsize=1)
def default_provider() -> LLMProvider:
    """The real provider, built once.

    Behind a function rather than a module-level `provider = AnthropicProvider()`
    for one reason that matters: constructing it reads the API key and builds an
    HTTP client, so at module scope merely *importing* this module required a
    key. That made the worker untestable without one and made `LLMProvider`
    being a Protocol a claim nothing could check. Now the provider is an
    argument with a default, and a fake is passed in rather than patched over.
    """
    from app.llm.anthropic_provider import AnthropicProvider  # noqa: PLC0415

    return AnthropicProvider()


async def drain(worker_id: str, *, provider: LLMProvider) -> int:
    """Claim and run until the queue is empty, or until asked to stop."""
    count = 0
    while not shutdown.requested.is_set():
        async with SessionFactory() as session:
            task = await task_service.claim_next(session, worker_id=worker_id)
        if task is None:
            return count
        await execute(task, provider=provider)
        count += 1
    return count


async def tick(worker_id: str, *, provider: LLMProvider | None = None) -> int:
    """One pass of the loop: due schedules, dead workers, then drain.

    Everything `run_forever` does except waiting — which is what makes it
    callable from a test without an infinite loop to escape from.
    """
    async with SessionFactory() as session:
        await task_service.expand_due_schedules(session)
        await task_service.sweep_stale(session)
    return await drain(worker_id, provider=provider or default_provider())


async def run_forever() -> None:
    host = socket.gethostname()
    # host:pid:nonce. The nonce is not decoration: in a container the worker is
    # PID 1 and the hostname survives a restart, so host:pid alone names the
    # dead process and its replacement identically — and a restarted worker
    # could not tell its predecessor's orphaned task from its own.
    worker_id = f"{host}:{os.getpid()}:{secrets.token_hex(4)}"
    logger.info("worker starting", worker_id=worker_id)

    # Before claiming anything new: a turn this container's previous worker
    # died in the middle of goes back on the queue now, not in
    # `task_stale_seconds`. See `task_service.release_orphans`.
    async with SessionFactory() as session:
        await task_service.release_orphans(session, host=host, worker_id=worker_id)

    shutdown.install_signal_handlers()
    provider = default_provider()

    await bus.start()

    try:
        async with bus.subscribe(task_service.WAKE_CHANNEL) as wake:
            while not shutdown.requested.is_set():
                await tick(worker_id, provider=provider)

                # Proof of a completed pass, for the healthcheck. After the
                # tick, not before: what matters is that the loop came back
                # round, not that it started.
                settings.worker_heartbeat_path.touch()

                # Woken by NOTIFY the instant something is enqueued; the timeout
                # is only so schedules and dead workers get noticed on a quiet
                # system. Shutdown wakes it too, so a SIGTERM during an idle
                # wait exits now rather than after the full interval.
                waiters = [
                    asyncio.ensure_future(wake.get()),
                    asyncio.ensure_future(shutdown.requested.wait()),
                ]
                done, pending = await asyncio.wait(
                    waiters,
                    timeout=settings.worker_idle_seconds,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()
                for task in done:
                    task.exception()  # retrieved so asyncio does not warn
    finally:
        await bus.stop()
        await engine.dispose()
        logger.info("worker stopped", worker_id=worker_id)


def main() -> None:
    configure_logging()
    asyncio.run(run_forever())
