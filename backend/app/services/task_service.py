"""The queue.

Postgres is the whole thing. The parts that matter are all in the SQL below:

* **Claiming** is `select … for update skip locked`. Two workers running the
  same query take different rows instead of one waiting on the other, and a
  crashed worker's row stays locked only as long as its transaction lives.
* **Waking** is NOTIFY on one global channel. Without it a worker polls and
  every chat turn waits half a poll interval for no reason.
* **Sweeping** is what makes the claim safe. A worker that is killed mid-task
  leaves a row marked running forever; nothing in Postgres notices, because
  nothing in Postgres knows the worker existed. The sweeper is that knowledge.

Read those three together and you have the design. Everything else here is
bookkeeping.
"""

import uuid
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import exists, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.bus import publish
from app.config import settings
from app.logging import get_logger
from app.models import Schedule, Task

logger = get_logger(__name__)

# One channel for "there is work", rather than one per kind. The worker's next
# move after waking is to ask the database anyway.
WAKE_CHANNEL = "tasks_new"

# A task is terminal when nothing will move it again. The streaming endpoint
# uses this to decide when to hang up.
TERMINAL_STATUSES = frozenset({"succeeded", "failed", "cancelled", "superseded"})

# Why a turn is stopping early. Two values rather than a bool because the
# worker does opposite things with them — see `stop_reason`.
StopReason = Literal["cancelled", "superseded"]

_CLAIM = text(
    """
    with claimed as (
        select id from tasks
         where status = 'pending' and run_at <= now()
         order by run_at
           for update skip locked
         limit 1
    )
    update tasks t
       set status = 'running',
           attempts = t.attempts + 1,
           claimed_at = now(),
           claimed_by = :worker_id,
           updated_at = now()
      from claimed
     where t.id = claimed.id
    returning t.id
    """
)

_SWEEP = text(
    """
    update tasks
       set status = case when attempts >= max_attempts then 'failed' else 'pending' end,
           error = case when attempts >= max_attempts then 'worker died mid-task' else error end,
           claimed_at = null,
           claimed_by = null,
           updated_at = now()
     where status = 'running'
       and claimed_at < now() - make_interval(secs => :stale_seconds)
    returning id
    """
)

_RELEASE = text(
    """
    update tasks
       set status = 'pending', claimed_at = null, claimed_by = null, updated_at = now()
     where id = :task_id
    """
)

_RETRY = text(
    """
    update tasks
       set status = 'pending',
           claimed_at = null,
           claimed_by = null,
           error = :error,
           run_at = now() + make_interval(secs => :delay),
           updated_at = now()
     where id = :task_id
    """
)

_DUE_SCHEDULES = text(
    """
    with due as (
        select id from schedules
         where enabled and next_run_at <= now()
         order by next_run_at
           for update skip locked
         limit 25
    )
    update schedules s
       set next_run_at = now() + make_interval(secs => s.interval_seconds),
           updated_at = now()
      from due
     where s.id = due.id
    returning s.id
    """
)


async def enqueue(
    session: AsyncSession,
    *,
    kind: str,
    conversation_id: uuid.UUID | None = None,
    payload: dict[str, Any] | None = None,
    run_at: datetime | None = None,
    request_id: str | None = None,
) -> Task:
    task = Task(
        kind=kind,
        conversation_id=conversation_id,
        payload=payload or {},
        request_id=request_id,
        **({"run_at": run_at} if run_at is not None else {}),
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)

    # Only worth waking a worker for something it can claim right now.
    if run_at is None:
        await publish(session, WAKE_CHANNEL, {"task_id": str(task.id)})

    logger.info("task enqueued", task_id=str(task.id), kind=kind)
    return task


async def claim_next(session: AsyncSession, *, worker_id: str) -> Task | None:
    """Take the oldest due task, or None. Safe to call from any number of workers."""
    result = await session.execute(_CLAIM, {"worker_id": worker_id})
    task_id = result.scalar()
    await session.commit()

    if task_id is None:
        return None

    # populate_existing, because the claim was a raw UPDATE and this session may
    # already hold a copy of that row from enqueueing it. With
    # expire_on_commit=False a plain get() would hand back the stale copy — and
    # `attempts` is exactly what the retry decision reads, so a stale one
    # silently gets the retry budget wrong.
    task = await session.get(Task, task_id, populate_existing=True)
    logger.info("task claimed", task_id=str(task_id), worker_id=worker_id)
    return task


async def finish(
    session: AsyncSession, *, task: Task, status: str, error: str | None = None
) -> None:
    """Settle a task permanently."""
    task.status = status
    task.error = error
    # func.now() rather than a Python timestamp: every other time in this table
    # comes from Postgres, and two clocks in one table means any ordering
    # question is decided by container clock skew.
    task.updated_at = func.now()
    await session.commit()
    logger.info("task finished", task_id=str(task.id), status=status)


async def release(session: AsyncSession, *, task: Task) -> None:
    """Put a claimed task back on the queue, unchanged.

    For a worker shutting down cleanly: it did not fail, it just will not be
    the one to finish it. Another worker picks it up on its next claim, which
    is seconds — rather than the `task_stale_seconds` the sweeper would take to
    reach the same conclusion about a worker that vanished without saying so.

    `attempts` is deliberately NOT decremented. A task that keeps being handed
    around deserves to hit `max_attempts` eventually; that is the difference
    between an unlucky task and one that kills whatever picks it up.
    """
    await session.execute(_RELEASE, {"task_id": task.id})
    await session.commit()
    logger.info("task released", task_id=str(task.id), attempts=task.attempts)


async def retry_later(
    session: AsyncSession, *, task: Task, error: str, delay_seconds: float
) -> None:
    """Requeue a failed task to run again after a delay."""
    await session.execute(_RETRY, {"task_id": task.id, "error": error, "delay": delay_seconds})
    await session.commit()
    logger.warning(
        "task retrying",
        task_id=str(task.id),
        attempt=task.attempts,
        max_attempts=task.max_attempts,
        delay_seconds=round(delay_seconds, 1),
    )


def retry_delay_seconds(attempts: int) -> float:
    """Exponential backoff, capped.

    Doubling matters more than the exact numbers: the failures worth retrying
    are rate limits and provider outages, and hammering either one is how a
    transient problem becomes a sustained one.
    """
    return min(
        settings.task_retry_base_seconds * (2 ** max(0, attempts - 1)),
        settings.task_retry_max_seconds,
    )


async def stop_reason(session: AsyncSession, *, task_id: uuid.UUID) -> StopReason | None:
    """Why this turn should stop, or None to carry on.

    Cooperative, because the worker is a different process and cannot be
    interrupted from outside. The caller checks this at event boundaries, so a
    stop takes effect within a token or two rather than instantly.

    **The two answers are not interchangeable, and that is the whole reason
    this returns a reason rather than a bool.** `cancelled` keeps whatever was
    generated; `superseded` throws it away. See `supersede_active` for why.
    """
    result = await session.execute(
        select(Task.cancel_requested, Task.status).where(Task.id == task_id)
    )
    row = result.first()

    # The row is gone, so the conversation went with it — this task is a
    # cascade away from never having existed. There is nothing left to write
    # the partial text to, which makes it the discarding kind.
    if row is None:
        return "superseded"
    if row.status == "superseded":
        return "superseded"
    if row.cancel_requested or row.status in TERMINAL_STATUSES:
        return "cancelled"
    return None


async def get_task(session: AsyncSession, *, task_id: uuid.UUID) -> Task | None:
    return await session.get(Task, task_id)


async def task_exists(session: AsyncSession, *, task_id: uuid.UUID) -> bool:
    """Is this row still in the table?

    Not `get_task(...) is not None`, and the difference is the whole reason
    this exists. `session.get` answers from the identity map when the session
    has already loaded that row — which it always has, by the time a worker is
    settling a task it just ran — so it returns the in-memory instance without
    asking Postgres anything, and reports a row that was deleted underneath it
    as present. This selects a scalar instead, so there is nothing to serve
    from the identity map and the answer comes from the database.
    """
    result = await session.execute(select(exists().where(Task.id == task_id)))
    return bool(result.scalar())


async def active_task(session: AsyncSession, *, conversation_id: uuid.UUID) -> Task | None:
    """The task currently working on this conversation, if any."""
    result = await session.execute(
        select(Task)
        .where(
            Task.conversation_id == conversation_id,
            Task.status.in_(("pending", "running")),
        )
        .order_by(Task.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def request_cancel(session: AsyncSession, *, task: Task) -> None:
    task.cancel_requested = True
    # A task that has not started can be settled immediately; there is no worker
    # to cooperate with yet.
    if task.status == "pending":
        task.status = "cancelled"
    await session.commit()
    logger.info("task cancel requested", task_id=str(task.id), status=task.status)


async def supersede_active(session: AsyncSession, *, conversation_id: uuid.UUID) -> None:
    """Retire whatever was running when a newer message arrived.

    Without this, sending a second message while the first is still generating
    gives you two workers writing to one conversation, interleaving their
    events into nonsense. The newest message wins.

    **The row goes terminal immediately, even while a worker still holds it.**
    That is not an attempt to interrupt the worker — it cannot be, and it keeps
    generating until it next checks `stop_reason`. It is so that `active_task`
    stops naming a turn that is already obsolete the moment the newer one is
    enqueued: a browser reattaching in that window should be pointed at the
    turn that is going to answer it, not at the one on its way out.

    It is also how the worker learns *which* kind of stop this is, and the
    difference is the reason this is not simply `request_cancel`. A cancelled
    turn keeps whatever it had written, because that is all the user will ever
    get. **A superseded turn throws it away**, because the newer user message
    is already sitting after it in the log: flushing a half-sentence at that
    point files the answer to the old question *below* the question that
    replaced it, and leaves the next turn replaying a history that ends on an
    assistant turn. See CONVENTIONS.md > Sending while one is running.
    """
    existing = await active_task(session, conversation_id=conversation_id)
    if existing is None:
        return

    existing.cancel_requested = True
    existing.status = "superseded"
    existing.updated_at = func.now()
    await session.commit()
    logger.info("task superseded", task_id=str(existing.id), conversation_id=str(conversation_id))


_RELEASE_ORPHANS = text(
    """
    update tasks
       set status = case when attempts >= max_attempts then 'failed' else 'pending' end,
           error = case when attempts >= max_attempts then 'worker died mid-task' else error end,
           claimed_at = null,
           claimed_by = null,
           updated_at = now()
     where status = 'running'
       and split_part(claimed_by, ':', 1) = :host
       and claimed_by <> :worker_id
    returning id
    """
)


async def release_orphans(session: AsyncSession, *, host: str, worker_id: str) -> int:
    """At startup: put back what an earlier worker on this host left running.

    A worker id is `host:pid:nonce`, and a container runs one worker. So when
    one starts, any task still `running` under this host but another id was
    claimed by a process that no longer exists — killed, OOM'd, or crashed
    inside a C extension without a word, which has happened. Without this the
    sweeper gets to it after `task_stale_seconds`, and whoever asked watches a
    spinner for that long; with it, the restarted worker picks the turn up
    again within seconds and it runs from the top.

    The assumption is one worker process per host. Two on one machine — which
    nothing here does — would release each other's live work on every start.
    """
    result = await session.execute(_RELEASE_ORPHANS, {"host": host, "worker_id": worker_id})
    ids = [row[0] for row in result.all()]
    await session.commit()
    if ids:
        logger.warning("orphaned tasks released", count=len(ids), host=host)
    return len(ids)


async def sweep_stale(session: AsyncSession, *, stale_seconds: int | None = None) -> int:
    """Return tasks abandoned by a dead worker to the queue.

    `stale_seconds` is an argument rather than a straight settings read so a
    test can make a task stale without reaching into a global.
    """
    if stale_seconds is None:
        stale_seconds = settings.task_stale_seconds
    result = await session.execute(_SWEEP, {"stale_seconds": stale_seconds})
    ids = [row[0] for row in result.all()]
    await session.commit()
    if ids:
        logger.warning("tasks swept", count=len(ids))
    return len(ids)


async def expand_due_schedules(session: AsyncSession) -> list[Task]:
    """Turn every due schedule into an agent_run task.

    The advance is `now() + interval`, not `next_run_at + interval`: a worker
    that was offline for a day catches up with one run, not with a day's worth
    all at once. Missed runs are skipped, deliberately.
    """
    result = await session.execute(_DUE_SCHEDULES)
    schedule_ids = [row[0] for row in result.all()]
    await session.commit()

    tasks: list[Task] = []
    for schedule_id in schedule_ids:
        schedule = await session.get(Schedule, schedule_id)
        if schedule is None:
            continue
        tasks.append(
            await enqueue(
                session,
                kind="agent_run",
                payload={
                    "prompt": schedule.prompt,
                    "user_id": schedule.user_id,
                    "schedule_id": str(schedule.id),
                    "schedule_name": schedule.name,
                },
            )
        )
        logger.info("schedule fired", schedule_id=str(schedule.id), name=schedule.name)

    return tasks
