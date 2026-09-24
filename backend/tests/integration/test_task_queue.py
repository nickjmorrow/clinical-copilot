"""The queue: claiming, scheduling, supersession, sweeping.

These need a real Postgres. `for update skip locked` has no meaning without
concurrent transactions, and it is the property the whole worker design rests
on — if it ever silently stops holding, two workers run the same turn twice and
interleave their events into one conversation.
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from app.db import SessionFactory
from app.models import Schedule
from app.services import conversation_service, task_service


async def test_two_open_transactions_claim_different_rows(session):
    """The skip-locked test, written so that a regression fails instead of hangs.

    `asyncio.gather(claim_next(), claim_next())` would pass even without SKIP
    LOCKED, because claim_next commits before returning — it proves "two
    different rows" but not the property. Holding the first transaction open is
    what makes the second claim either succeed immediately (correct) or block
    forever (broken), and the timeout turns that hang into a readable failure.
    """
    first = await task_service.enqueue(session, kind="chat_turn")
    second = await task_service.enqueue(session, kind="chat_turn")

    async with SessionFactory() as s1, SessionFactory() as s2:
        claimed_a = (await s1.execute(task_service._CLAIM, {"worker_id": "w1"})).scalar()

        claimed_b = (
            await asyncio.wait_for(
                s2.execute(task_service._CLAIM, {"worker_id": "w2"}), timeout=5.0
            )
        ).scalar()

        assert claimed_a is not None
        assert claimed_b is not None
        assert {claimed_a, claimed_b} == {first.id, second.id}

        await s1.commit()
        await s2.commit()


async def test_a_task_scheduled_for_later_is_invisible_to_a_claim(session):
    """`run_at` is the entire scheduling mechanism."""
    await task_service.enqueue(
        session,
        kind="agent_run",
        run_at=datetime.now(UTC) + timedelta(hours=1),
    )
    assert await task_service.claim_next(session, worker_id="w") is None


async def test_supersede_retires_a_task_whether_or_not_a_worker_holds_it(session):
    """The row goes terminal immediately, running or not.

    Not an attempt to interrupt the worker — it cannot be, and it keeps
    generating until it next reads `stop_reason`. The point is that
    `active_task` stops naming an obsolete turn the instant a newer one is
    enqueued, so a browser reattaching in that window is pointed at the turn
    that will answer it. The flag is what the worker eventually cooperates with.
    """
    conversation = await conversation_service.create_conversation(session, user_id="dev-user")

    pending = await task_service.enqueue(session, kind="chat_turn", conversation_id=conversation.id)
    await task_service.supersede_active(session, conversation_id=conversation.id)
    await session.refresh(pending)
    assert pending.status == "superseded"

    running = await task_service.enqueue(session, kind="chat_turn", conversation_id=conversation.id)
    running.status = "running"
    await session.commit()

    await task_service.supersede_active(session, conversation_id=conversation.id)
    await session.refresh(running)
    assert running.status == "superseded"
    assert running.cancel_requested is True

    # And it is no longer what a reattaching browser would be handed.
    assert await task_service.active_task(session, conversation_id=conversation.id) is None


async def test_stop_reason_tells_a_cancelled_turn_from_a_superseded_one(session):
    """The worker keeps what a cancelled turn wrote and discards a superseded one.

    A bool cannot express that, which is why this returns a reason. Getting it
    backwards files a half-finished answer *below* the message that replaced it
    — see AGENTS.md > Sending while one is running.
    """
    conversation = await conversation_service.create_conversation(session, user_id="dev-user")

    task = await task_service.enqueue(session, kind="chat_turn", conversation_id=conversation.id)
    task.status = "running"
    await session.commit()
    assert await task_service.stop_reason(session, task_id=task.id) is None

    await task_service.request_cancel(session, task=task)
    assert await task_service.stop_reason(session, task_id=task.id) == "cancelled"

    superseded = await task_service.enqueue(
        session, kind="chat_turn", conversation_id=conversation.id
    )
    superseded.status = "running"
    await session.commit()
    await task_service.supersede_active(session, conversation_id=conversation.id)
    assert await task_service.stop_reason(session, task_id=superseded.id) == "superseded"

    # A row that vanished underneath the worker is the discarding kind too:
    # the conversation was deleted, so there is nothing left to write to.
    assert await task_service.stop_reason(session, task_id=uuid.uuid4()) == "superseded"


async def test_sweep_requeues_an_abandoned_task_then_fails_it_at_max_attempts(session):
    """The sweeper is the only thing that notices a worker that died.

    Nothing in Postgres knows a worker existed, so without this a killed process
    leaves a row marked `running` forever.
    """
    task = await task_service.enqueue(session, kind="chat_turn")
    await session.execute(
        text(
            "update tasks set status='running', attempts=1, claimed_at=now() - interval '1 hour'"
            " where id = :id"
        ),
        {"id": task.id},
    )
    await session.commit()

    assert await task_service.sweep_stale(session, stale_seconds=60) == 1
    await session.refresh(task)
    assert task.status == "pending"

    # Out of attempts: the next sweep gives up rather than looping forever.
    await session.execute(
        text(
            "update tasks set status='running', attempts=3, max_attempts=3,"
            " claimed_at=now() - interval '1 hour' where id = :id"
        ),
        {"id": task.id},
    )
    await session.commit()

    assert await task_service.sweep_stale(session, stale_seconds=60) == 1
    await session.refresh(task)
    assert task.status == "failed"
    assert task.error == "worker died mid-task"


async def test_a_restarted_worker_releases_only_what_its_dead_predecessor_held(session):
    """A worker that died mid-turn — a segfault in a C extension has done it,
    with no log line — left its task `running`. The next worker on the same
    host puts it back at once instead of in `task_stale_seconds`. Another
    host's live work, and its own, are left alone."""
    orphan = await task_service.enqueue(session, kind="chat_turn")
    elsewhere = await task_service.enqueue(session, kind="chat_turn")
    own = await task_service.enqueue(session, kind="chat_turn")
    # The same host and the same pid, which is what a restarted container
    # looks like: the worker is PID 1 both times. Only the nonce differs.
    claims = (
        (orphan, "host-a:1:dead0000"),
        (elsewhere, "host-b:1:f00d0000"),
        (own, "host-a:1:beef0000"),
    )
    for task, claimed_by in claims:
        await session.execute(
            text(
                "update tasks set status='running', attempts=1, claimed_at=now(),"
                " claimed_by=:by where id = :id"
            ),
            {"by": claimed_by, "id": task.id},
        )
    await session.commit()

    assert (
        await task_service.release_orphans(session, host="host-a", worker_id="host-a:1:beef0000")
        == 1
    )

    for task in (orphan, elsewhere, own):
        await session.refresh(task)
    assert (orphan.status, orphan.claimed_by) == ("pending", None)
    assert elsewhere.status == "running"
    assert own.status == "running"


async def test_a_due_schedule_becomes_a_task_and_is_not_fired_twice(session):
    schedule = Schedule(
        user_id="dev-user",
        name="hourly",
        prompt="do the thing",
        interval_seconds=3600,
    )
    session.add(schedule)
    await session.commit()

    created = await task_service.expand_due_schedules(session)
    assert len(created) == 1
    assert created[0].kind == "agent_run"
    assert created[0].payload["prompt"] == "do the thing"

    # next_run_at has moved an hour out, so a second pass finds nothing.
    assert await task_service.expand_due_schedules(session) == []


@pytest.mark.parametrize(
    ("attempts", "expected"),
    [(1, 5.0), (2, 10.0), (3, 20.0), (10, 120.0)],
)
def test_retry_backoff_doubles_and_caps(attempts: int, expected: float):
    assert task_service.retry_delay_seconds(attempts) == expected


async def test_release_returns_a_claimed_task_without_counting_it_as_failed(session):
    task = await task_service.enqueue(session, kind="chat_turn")
    claimed = await task_service.claim_next(session, worker_id="w1")
    assert claimed is not None
    assert claimed.attempts == 1

    await task_service.release(session, task=claimed)
    await session.refresh(task)
    assert task.status == "pending"
    assert task.claimed_by is None
    # Not decremented: a task handed around forever should still run out.
    assert task.attempts == 1


async def test_enqueue_defaults_come_from_the_database_not_just_the_orm(session):
    """Raw inserts must work too — task_service's own SQL does not go via the ORM."""
    await session.execute(text("insert into tasks (kind) values ('agent_run')"))
    await session.commit()
    row = (
        await session.execute(
            text("select status, attempts, max_attempts, cancel_requested, payload from tasks")
        )
    ).first()
    assert row is not None
    assert row.status == "pending"
    assert (row.attempts, row.max_attempts, row.cancel_requested) == (0, 3, False)
    assert row.payload == {}


async def test_check_constraints_are_enforced_by_the_database(session):
    """Declared on the models so Alembic emits them; asserted here so they stay.

    They exist only because models.py declares them — the drift that made this
    worth checking is that they once existed only in hand-written SQL, and
    autogenerating against the models would have dropped them silently.
    """
    with pytest.raises(Exception, match="tasks_kind_check"):
        await session.execute(text("insert into tasks (kind) values ('nonsense')"))
    await session.rollback()

    conversation = await conversation_service.create_conversation(session, user_id="dev-user")
    with pytest.raises(Exception, match="event_records_type_check"):
        await session.execute(
            text(
                "insert into event_records (conversation_id, type, data)"
                " values (:cid, 'nope', '{}'::jsonb)"
            ),
            {"cid": conversation.id},
        )
    await session.rollback()
