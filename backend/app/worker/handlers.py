"""What each kind of task means, and how its row is settled afterwards.

`execute` at the bottom is the one entry point: it runs a claimed task,
survives anything the turn throws at it, and leaves the row in a state the queue
agrees with. The two `_run_*` functions above it are the per-kind bodies, and
both delegate the actual turn to `turn.generate`.

Most of the length here is `execute`'s settle path, and most of *that* is two
comments about the ways a conversation deleted mid-turn used to wedge the
worker. Read them before touching it.
"""

import asyncio
import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.bus import channel_for, publish
from app.config import DEV_USER_ID, settings
from app.db import SessionFactory
from app.llm.base import LLMProvider
from app.logging import get_logger
from app.models import Task
from app.services import conversation_service, definition_service, task_service, transcript_service
from app.worker.turn import TurnOutcome, already_answered, generate, name_conversation

logger = get_logger(__name__)


async def _publish_status(session: AsyncSession, conversation_id: uuid.UUID, task: Task) -> None:
    await publish(
        session,
        channel_for(conversation_id),
        {
            "type": "status",
            "taskId": str(task.id),
            "status": task.status,
            # Carried so a browser can say what went wrong rather than "failed".
            "error": task.error,
        },
    )


async def _run_chat_turn(
    session: AsyncSession, task: Task, *, provider: LLMProvider
) -> TurnOutcome:
    if task.conversation_id is None:
        return TurnOutcome("failed", error="chat_turn task has no conversation")

    history = await transcript_service.load_history(session, conversation_id=task.conversation_id)

    # The work was already done; only the bookkeeping was lost. A worker killed
    # outright (SIGKILL, OOM) after writing its answer leaves a task the sweeper
    # requeues, and calling the model again would bill twice for a second copy
    # of an answer the conversation already has. It would also be rejected —
    # generation requires history to end on a user turn.
    if already_answered(history):
        logger.info("turn already answered, settling", task_id=str(task.id))
        return TurnOutcome("succeeded")

    # A conversation is named from its opening message, beside the turn rather
    # than after it. Both halves of that matter.
    #
    # *From the opening message*, because that is what a name is for — the
    # answer adds length, cost and very little else, and waiting for it would
    # mean the sidebar showed a truncated sentence for the entire first turn.
    #
    # *Beside*, because a cheap model still takes the better part of a second,
    # and every way of spending that serially is visible: before generation it
    # delays the first token, and after it holds the task `running` — which is
    # what the browser reads as "still answering", so the composer stays
    # disabled with the answer already on screen. Generation outlasts a title
    # call by an order of magnitude, so awaiting it in the `finally` below
    # costs nothing and leaves no task outliving the turn.
    namer = (
        asyncio.create_task(name_conversation(task.conversation_id, history, provider))
        if len(history) == 1
        else None
    )

    try:
        return await generate(
            session,
            task,
            conversation_id=task.conversation_id,
            system=await definition_service.with_vocabulary(session, base=settings.system_prompt),
            messages=history,
            provider=provider,
        )
    finally:
        if namer is not None:
            await namer


async def _run_agent_run(
    session: AsyncSession, task: Task, *, provider: LLMProvider
) -> TurnOutcome:
    """A scheduled run, with nobody watching.

    It gets a real conversation of its own, which means the transcript of what
    an agent did at 3am is readable in the same UI as everything else — no
    second viewer to build, and the event log already knew how to store tool
    calls.
    """
    prompt = task.payload.get("prompt")
    if not prompt:
        return TurnOutcome("failed", error="agent_run task has no prompt")

    # A re-run of this task — released at shutdown, or swept after a worker
    # died — already has a conversation and already wrote its prompt into it.
    # Creating another would orphan the first and duplicate the transcript.
    if task.conversation_id is not None:
        conversation_id = task.conversation_id
    else:
        conversation = await conversation_service.create_conversation(
            session, user_id=task.payload.get("user_id", DEV_USER_ID)
        )
        if name := task.payload.get("schedule_name"):
            conversation.title = name

        # Recorded on the task so the run is traceable from either direction.
        task.conversation_id = conversation.id
        await session.commit()

        await transcript_service.add_user_message(session, conversation=conversation, text=prompt)
        conversation_id = conversation.id

    history = await transcript_service.load_history(session, conversation_id=conversation_id)
    if already_answered(history):
        logger.info("agent run already answered, settling", task_id=str(task.id))
        return TurnOutcome("succeeded")

    return await generate(
        session,
        task,
        conversation_id=conversation_id,
        system=await definition_service.with_vocabulary(session, base=settings.agent_system_prompt),
        messages=history,
        provider=provider,
    )


async def execute(task: Task, *, provider: LLMProvider) -> None:
    """Run one claimed task and settle its row, whatever happens."""
    # Re-bind the request id the API recorded when it enqueued this, so one
    # `grep` finds both halves of a turn across two processes. Null for work the
    # worker created itself, like a scheduled run, which gets the task id alone.
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(task_id=str(task.id))
    if task.request_id:
        structlog.contextvars.bind_contextvars(request_id=task.request_id)

    # Captured before the turn, so the error path never has to read an
    # attribute off an instance a failed flush may have expired.
    task_id = task.id

    async with SessionFactory() as session:
        task = await session.merge(task)
        rolled_back = False
        try:
            if task.kind == "chat_turn":
                outcome = await _run_chat_turn(session, task, provider=provider)
            elif task.kind == "agent_run":
                outcome = await _run_agent_run(session, task, provider=provider)
            else:
                outcome = TurnOutcome("failed", error=f"unknown task kind {task.kind!r}")
        except Exception as exc:
            # The worker outlives every task it runs. A handler that raises
            # marks its own row failed and the loop continues — the alternative
            # is one bad turn taking the queue down with it. Retryable, because
            # an unexpected exception is more often a blip than a certainty.
            #
            # **Roll back first, before anything else touches this session.** A
            # failed flush — an IntegrityError above all, which is what a
            # conversation deleted mid-turn produces — leaves the session
            # refusing every further statement until it is rolled back, and it
            # expires every instance it holds. `task_id` below is the local
            # captured at the top for that reason: reading `task.id` here would
            # lazy-load an expired attribute, which is a statement, which
            # raises PendingRollbackError *from inside the logging call*. The
            # exception then escapes the `try` whose whole job is to contain it
            # and the worker stops claiming anything, forever.
            await session.rollback()
            rolled_back = True
            logger.exception("task raised", task_id=str(task_id))
            outcome = TurnOutcome("failed", error=f"{type(exc).__name__}: {exc}", retryable=True)

        # The conversation can be deleted while its turn is running — from
        # another tab, or from this one — and the cascade takes this task row
        # with it. There is then nothing to settle and nobody to tell, and
        # every statement below would be an UPDATE matching zero rows.
        #
        # `task_exists` and not `get_task`, deliberately: this session loaded
        # that row before the turn, so `session.get` answers from the identity
        # map without asking Postgres and cheerfully reports a deleted row as
        # present. The settle below then UPDATEs zero rows, SQLAlchemy raises
        # StaleDataError, and the worker is wedged for the second time by the
        # same delete.
        if not await task_service.task_exists(session, task_id=task_id):
            logger.info("task vanished mid-run", task_id=str(task_id))
            structlog.contextvars.clear_contextvars()
            return

        if rolled_back:
            # The rollback above expired every instance the session held,
            # `task` included, and every read below this point — `.attempts`,
            # `.max_attempts`, `.conversation_id` — is a plain attribute
            # access, not an `await`. On an expired instance that lazy-loads,
            # which is exactly the MissingGreenlet the comment above is
            # already warning about one frame up, just one statement later:
            # this used to crash *inside* the retry check itself, on the
            # first `task.` read after a rollback the exception handler had
            # already survived. Refreshing now, while still inside an
            # `await`, is what keeps every read below safe. Never raises
            # `ObjectDeletedError` here — the `task_exists` check just above
            # already confirmed the row is still there.
            await session.refresh(task)

        # Shutting down: hand the work back rather than settle it. Nothing about
        # this task failed, and the next worker to claim it resumes from the
        # events already on disk.
        if outcome.status == "interrupted":
            await task_service.release(session, task=task)

        # Worth another go, and attempts left. `attempts` was incremented by the
        # claim, so it already counts this one.
        elif outcome.status == "failed" and outcome.retryable and task.attempts < task.max_attempts:
            await task_service.retry_later(
                session,
                task=task,
                error=outcome.error or "",
                delay_seconds=task_service.retry_delay_seconds(task.attempts),
            )

        else:
            await task_service.finish(
                session, task=task, status=outcome.status, error=outcome.error
            )

        # Always published, including for a release or a retry: those leave the
        # task non-terminal, which is exactly what tells a watching browser to
        # keep waiting rather than give up.
        if task.conversation_id is not None:
            await session.refresh(task)
            await _publish_status(session, task.conversation_id, task)

    structlog.contextvars.clear_contextvars()
