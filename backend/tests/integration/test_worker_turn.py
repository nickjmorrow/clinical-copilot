"""A whole turn, driven by the worker, against a scripted provider.

The single highest-coverage test in the suite runs through `_drain` ->
`claim_next` -> `_execute` -> `_run_chat_turn` -> `load_history` -> `_generate`
-> every `conversation_service.add_*` -> `finish`, without touching the network.
"""

import asyncio

import pytest
from sqlalchemy import select

from app.db import SessionFactory
from app.llm.types import AssistantMessage, ToolCall, ToolResult
from app.models import Conversation, UsageEvent
from app.services import conversation_service, task_service, transcript_service
from app.worker import handlers, loop, turn
from tests.support.fakes import FakeProvider, HangingProvider, calls_tool_then_says, fails, says


@pytest.fixture
async def conversation(session) -> Conversation:
    return await conversation_service.create_conversation(session, user_id="dev-user")


async def test_a_turn_with_a_tool_call_persists_every_event_and_succeeds(session, conversation):
    # The clinical dataset is seeded once for the whole session — see
    # tests/integration/conftest.py — not reseeded here.
    await transcript_service.add_user_message(
        session,
        conversation=conversation,
        text="which patients are on a nephrotoxic medication with impaired kidney function?",
    )
    await task_service.enqueue(session, kind="chat_turn", conversation_id=conversation.id)

    provider = FakeProvider(
        calls_tool_then_says(
            tool="find_patients",
            args={
                "question": "which patients are on a nephrotoxic medication with "
                "impaired kidney function?",
                "terms": ["impaired renal function", "nephrotoxic medication"],
                "measures": [],
                "group_by": [],
                "columns": [],
            },
            text="8 patients match.",
        )
    )
    assert await loop.drain("test-worker", provider=provider) == 1

    records = await transcript_service.events_since(
        session, conversation_id=conversation.id, since=0
    )
    assert [r.type for r in records] == [
        "user_message",
        "assistant_message",  # empty: the response that was only a tool call
        "tool_call",
        "tool_result",
        "assistant_message",
    ]
    assert records[1].data["text"] == ""
    assert records[-1].data["text"] == "8 patients match."

    # The real tool registry ran, not a canned answer — and with it the whole
    # clinical path: term resolution, the assembler, the guardrails, the audit
    # write. This is the only test that exercises all of it through the worker.
    assert provider.executed[0][0] == "find_patients"
    stored = records[3].data["content"]
    assert "8 matching patient(s)" in stored
    assert "impaired renal function" in stored

    # load_history actually reached the provider, folded.
    assert [m.role for m in provider.calls[0]["messages"]] == ["user"]
    # aclose() in _generate's finally still happens.
    assert provider.closed is True


async def test_a_turn_meters_its_tokens_where_deleting_the_conversation_cannot_reach(
    session, conversation
):
    """The daily budget is only a ceiling if spending cannot be erased. Tokens
    are written to `usage_events`, under the conversation's owner, and stay
    there after the conversation — and its transcript — is deleted."""
    await transcript_service.add_user_message(session, conversation=conversation, text="hello")
    await task_service.enqueue(session, kind="chat_turn", conversation_id=conversation.id)

    assert await loop.drain("test-worker", provider=FakeProvider(says("Hello there"))) == 1
    await conversation_service.delete_conversation(session, conversation=conversation)

    rows = (await session.scalars(select(UsageEvent).where(UsageEvent.kind == "tokens"))).all()
    assert [(row.user_id, row.amount > 100) for row in rows] == [("dev-user", True)]


async def test_a_large_tool_result_does_not_crash_the_worker(session, conversation):
    """Regression case for the worker/NOTIFY bug.

    A `tool_result` this large used to reach `bus.publish`, which handed it to
    `select pg_notify(...)`, which Postgres refused past 8000 bytes — raising
    `DBAPIError` out of the middle of a turn and crashing the worker. The fix
    lives in `bus.publish` itself (see `tests/integration/test_bus.py`); this
    test is the same failure mode one layer up, through the real worker path
    that used to hit it, asserting the turn completes normally rather than
    that any particular function was called.
    """
    await transcript_service.add_user_message(
        session, conversation=conversation, text="list a cohort"
    )
    task = await task_service.enqueue(session, kind="chat_turn", conversation_id=conversation.id)

    oversized_result = "x" * 9000
    provider = FakeProvider(
        [
            AssistantMessage(text="", input_tokens=100, output_tokens=20),
            ToolCall(tool_use_id="toolu_big", name="find_patients", input={}),
            ToolResult(tool_use_id="toolu_big", content=oversized_result, is_error=False),
            *says("here is the cohort"),
        ]
    )
    assert await loop.drain("test-worker", provider=provider) == 1

    await session.refresh(task)
    assert task.status == "succeeded"

    records = await transcript_service.events_since(
        session, conversation_id=conversation.id, since=0
    )
    assert [r.type for r in records] == [
        "user_message",
        "assistant_message",
        "tool_call",
        "tool_result",
        "assistant_message",
    ]
    # The oversized event is durably written even though it was never
    # published live — that is the whole point of "dropped, not raised".
    assert records[3].data["content"] == oversized_result
    assert records[-1].data["text"] == "here is the cohort"


async def test_a_failed_flush_mid_turn_is_retried_without_crashing_the_settle_path(
    session, conversation
):
    """Regression case for the second half of the same worker/NOTIFY bug:
    once something genuinely fails to flush mid-
    turn, `execute`'s own `session.rollback()` used to leave `task` expired,
    and the very next read of `task.attempts` — deciding whether to retry —
    crashed with `MissingGreenlet` instead of ever retrying anything.

    Needs a real DBAPIError, not just a Python exception — a plain
    `raise RuntimeError()` never touches the session, never leaves it needing
    a rollback, and does not exercise the expired-instance path at all. A NUL
    byte in a `tool_result`'s content is a reliable, deterministic way to get
    a real one: Postgres's JSONB rejects `\\u0000` outright, so writing it
    fails the same way a conversation deleted mid-turn does — see CONVENTIONS.md's
    "Roll back before the error path touches anything".
    """
    await transcript_service.add_user_message(session, conversation=conversation, text="hi")
    task = await task_service.enqueue(session, kind="chat_turn", conversation_id=conversation.id)

    provider = FakeProvider(
        [
            AssistantMessage(text="", input_tokens=100, output_tokens=20),
            ToolCall(tool_use_id="toolu_nul", name="find_patients", input={}),
            ToolResult(tool_use_id="toolu_nul", content="bad\x00byte", is_error=False),
        ]
    )
    await loop.drain("test-worker", provider=provider)

    await session.refresh(task)
    assert task.status == "pending", "a retryable failure should be requeued, not stuck"
    assert task.attempts == 1
    assert task.error is not None
    assert "DBAPIError" in task.error


async def test_a_stream_error_fails_the_task_and_keeps_the_provider_code(session, conversation):
    await transcript_service.add_user_message(session, conversation=conversation, text="hi")
    task = await task_service.enqueue(session, kind="chat_turn", conversation_id=conversation.id)

    await loop.drain("test-worker", provider=FakeProvider(fails("auth_failed", "Bad key.")))

    await session.refresh(task)
    assert task.status == "failed"
    assert task.error == "auth_failed: Bad key."
    # Not retryable: a wrong key is wrong on every attempt.
    assert task.attempts == 1


async def test_a_retryable_failure_is_requeued_rather_than_settled(session, conversation):
    await transcript_service.add_user_message(session, conversation=conversation, text="hi")
    task = await task_service.enqueue(session, kind="chat_turn", conversation_id=conversation.id)

    await loop.drain("test-worker", provider=FakeProvider(fails("rate_limited", "Slow down.")))

    await session.refresh(task)
    assert task.status == "pending"
    assert task.attempts == 1
    assert task.claimed_by is None
    # Scheduled into the future, so _drain does not immediately pick it up again.
    assert task.run_at > task.created_at


async def test_cancelling_mid_stream_keeps_the_text_written_so_far(session, conversation):
    """ "A cancelled turn is a shorter turn, not a discarded one" — in a test.

    That sentence appears three times in the documentation and `flush_partial`
    is the only code implementing it.
    """
    await transcript_service.add_user_message(session, conversation=conversation, text="essay")
    task = await task_service.enqueue(session, kind="chat_turn", conversation_id=conversation.id)
    claimed = await task_service.claim_next(session, worker_id="test-worker")
    assert claimed is not None

    async def cancel_shortly():
        await asyncio.sleep(0.2)
        async with SessionFactory() as s:
            fresh = await task_service.get_task(s, task_id=task.id)
            assert fresh is not None
            await task_service.request_cancel(s, task=fresh)

    original = turn.CANCEL_POLL_SECONDS
    turn.CANCEL_POLL_SECONDS = 0.0
    try:
        canceller = asyncio.ensure_future(cancel_shortly())
        await handlers.execute(claimed, provider=HangingProvider())
        await canceller
    finally:
        turn.CANCEL_POLL_SECONDS = original

    await session.refresh(task)
    assert task.status == "cancelled"

    records = await transcript_service.events_since(
        session, conversation_id=conversation.id, since=0
    )
    written = [r for r in records if r.type == "assistant_message"]
    assert written, "the partial answer was not written down"
    assert written[-1].data["text"].startswith("token")


async def test_a_superseding_message_discards_the_partial_instead_of_filing_it_late(
    session, conversation
):
    """The other half of the sentence above: a SUPERSEDED turn is discarded.

    The asymmetry with cancellation is not fussiness. Supersession writes a new
    user message into the log first, so by the time the retired worker notices,
    anything it flushes lands *after* the question that replaced it — a stray
    half-answer to the old question sitting below the new one, and a history
    that ends on an assistant turn for the turn about to run. Discarding is what
    keeps the log in the order things were said.

    Deliberately driven through the same two calls the route makes, in the same
    order, because the order is the entire point.
    """
    await transcript_service.add_user_message(session, conversation=conversation, text="essay")
    task = await task_service.enqueue(session, kind="chat_turn", conversation_id=conversation.id)
    claimed = await task_service.claim_next(session, worker_id="test-worker")
    assert claimed is not None

    async def send_another_shortly():
        await asyncio.sleep(0.2)
        async with SessionFactory() as s:
            # Exactly what POST /messages does, in its order.
            await task_service.supersede_active(s, conversation_id=conversation.id)
            fresh = await s.get(Conversation, conversation.id)
            assert fresh is not None
            await transcript_service.add_user_message(s, conversation=fresh, text="actually, no")

    original = turn.CANCEL_POLL_SECONDS
    turn.CANCEL_POLL_SECONDS = 0.0
    try:
        sender = asyncio.ensure_future(send_another_shortly())
        await handlers.execute(claimed, provider=HangingProvider())
        await sender
    finally:
        turn.CANCEL_POLL_SECONDS = original

    await session.refresh(task)
    assert task.status == "superseded"

    records = await transcript_service.events_since(
        session, conversation_id=conversation.id, since=0
    )
    assert [r.type for r in records] == ["user_message", "user_message"], (
        "the retired turn flushed its partial answer below the message that replaced it"
    )

    # And so the next turn is handed a history it can actually generate from,
    # rather than one ending on a truncated assistant turn.
    history = await transcript_service.load_history(session, conversation_id=conversation.id)
    assert history[-1].role == "user"


async def test_a_turn_already_answered_is_settled_without_calling_the_model(session, conversation):
    """A worker killed after writing its answer must not bill for a second one."""
    await transcript_service.add_user_message(session, conversation=conversation, text="hi")
    await transcript_service.add_assistant_message(
        session, conversation_id=conversation.id, text="already answered"
    )
    task = await task_service.enqueue(session, kind="chat_turn", conversation_id=conversation.id)

    provider = FakeProvider(says("this should never be produced"))
    await loop.drain("test-worker", provider=provider)

    await session.refresh(task)
    assert task.status == "succeeded"
    assert provider.calls == [], "the model was called for a turn that was already answered"


async def test_an_agent_run_creates_its_own_conversation_and_reuses_it_on_a_rerun(session):
    task = await task_service.enqueue(
        session,
        kind="agent_run",
        payload={"prompt": "check the time", "user_id": "dev-user", "schedule_name": "Hourly"},
    )

    provider = FakeProvider(says("done"))
    await loop.drain("test-worker", provider=provider)

    await session.refresh(task)
    assert task.status == "succeeded"
    assert task.conversation_id is not None
    first_conversation = task.conversation_id

    records = await transcript_service.events_since(
        session, conversation_id=first_conversation, since=0
    )
    assert [r.type for r in records] == ["user_message", "assistant_message"]
    assert provider.calls[0]["system"].startswith("You are an agent running on a schedule")

    # Re-run it, as a release or a sweep would: same conversation, no duplicate.
    task.status = "pending"
    await session.commit()
    await loop.drain("test-worker", provider=FakeProvider(says("again")))
    await session.refresh(task)
    assert task.conversation_id == first_conversation
