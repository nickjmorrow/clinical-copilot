"""One turn: ask the model, run what it asked for, write down what happened.

This is the engine. `generate` consumes the adapter's event stream and turns
each event into a durable row plus a frame on the bus, checking for a Stop at
every durable event and roughly once a second while tokens flow.

It knows nothing about task kinds, claiming or settling — that is
`handlers.py` — and nothing about the process loop, which is `loop.py`.
"""

import time
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.bus import channel_for, publish
from app.config import DEV_USER_ID
from app.db import SessionFactory
from app.llm.base import LLMProvider
from app.llm.types import (
    RETRYABLE_ERROR_CODES,
    AssistantMessage,
    ChatMessage,
    StreamDone,
    StreamError,
    TextDelta,
    ThinkingDelta,
    ToolCall,
    ToolResult,
)
from app.logging import get_logger
from app.models import Task
from app.services import conversation_service, task_service, transcript_service, usage_service
from app.tools import definitions as tool_definitions
from app.tools import executor as tool_executor
from app.tools.base import ToolContext
from app.wire import event_frame
from app.worker import shutdown

logger = get_logger(__name__)

# How often to ask the database whether someone pressed Stop, while tokens are
# streaming. Durable events are rare enough to check on every one; tokens are
# not, and a query per token would cost more than the generation. One second is
# below what anyone perceives and is ~1/50th of the queries.
CANCEL_POLL_SECONDS = 1.0


@dataclass(frozen=True, slots=True)
class TurnOutcome:
    """How a turn ended, and what should happen to its task row.

    `status` is a task status, except for the extra `interrupted`, which never
    reaches the database: it means "this worker is going away, someone else
    should finish this" and resolves to a release rather than a settlement.
    """

    status: str
    error: str | None = None
    retryable: bool = False


async def generate(
    session: AsyncSession,
    task: Task,
    *,
    conversation_id: uuid.UUID,
    system: str,
    messages: list[ChatMessage],
    provider: LLMProvider,
) -> TurnOutcome:
    """Run one turn to completion, writing and publishing as it goes.

    Every event is durable before it is announced, so a browser that reconnects
    mid-turn and replays from its cursor sees exactly what a browser that stayed
    connected saw.

    Stops early for three reasons, at the same checkpoints: someone pressed
    Stop, a newer message superseded this turn, or this worker is shutting down.
    Only the first flushes what it had written — a cancelled turn is a shorter
    turn, not a discarded one. The other two deliberately do not, for opposite
    reasons: a superseded turn has been overtaken in the log and would file its
    half-sentence below the message that replaced it, and an interrupted one is
    about to be run again from the top.
    """
    channel = channel_for(conversation_id)

    # The tool context is built here, once, rather than threaded through every
    # handler. `owner_of` rather than a value passed down: the audit log records
    # who a clinical question was asked by, and the authoritative answer to that
    # is the conversation row, not whatever the caller believed.
    tool_context = ToolContext(
        session=session,
        user_id=await conversation_service.owner_of(session, conversation_id=conversation_id)
        or DEV_USER_ID,
        conversation_id=conversation_id,
    )

    # Tokens seen since the last durable row. Only needed if the turn is
    # CANCELLED: that should be a shorter turn, not a discarded one, and without
    # this the half-sentence on the user's screen would vanish on the next
    # refresh because nothing ever wrote it down. Supersession and shutdown both
    # drop it instead; see the docstring.
    partial: list[str] = []

    async def flush_partial() -> None:
        if not partial:
            return
        record = await transcript_service.add_assistant_message(
            session, conversation_id=conversation_id, text="".join(partial)
        )
        partial.clear()
        frame = event_frame(record)
        if frame is not None:
            await publish(session, channel, frame)

    stream = provider.stream(
        system=system,
        messages=messages,
        tools=tool_definitions(),
        execute_tool=tool_executor(tool_context),
    )
    last_cancel_check = time.monotonic()

    try:
        async for event in stream:
            match event:
                # Tokens are published and not stored. They are worth showing
                # and not worth a row; the authoritative text arrives moments
                # later as an assistant_message and replaces them.
                case TextDelta() | ThinkingDelta():
                    kind = "text" if isinstance(event, TextDelta) else "thinking"
                    if kind == "text":
                        partial.append(event.text)
                    await publish(session, channel, {"type": kind, "text": event.text})

                    # Rate-limited, because a turn with no tool calls has no
                    # other boundary until it is finished — and "Stop" that only
                    # takes effect once the answer is complete is not a stop.
                    # Deliberately WITHOUT flushing the partial text. A
                    # cancelled turn keeps what it wrote because that is all the
                    # user will ever get; an interrupted one is about to be run
                    # again from the top, so keeping it would both duplicate the
                    # answer and — because the replay would then end on an
                    # assistant turn — be rejected outright as a prefill.
                    if shutdown.requested.is_set():
                        return TurnOutcome("interrupted")

                    now = time.monotonic()
                    if now - last_cancel_check >= CANCEL_POLL_SECONDS:
                        last_cancel_check = now
                        reason = await task_service.stop_reason(session, task_id=task.id)
                        if reason is not None:
                            # Only a cancellation keeps what it wrote. A
                            # superseded turn discards it, because a newer user
                            # message is already in the log after this point and
                            # flushing here would file the old answer below the
                            # question that replaced it.
                            if reason == "cancelled":
                                await flush_partial()
                            return TurnOutcome(reason)
                    continue

                case AssistantMessage():
                    # The durable row supersedes whatever was accumulated for it.
                    partial.clear()
                    record = await transcript_service.add_assistant_message(
                        session,
                        conversation_id=conversation_id,
                        text=event.text,
                        input_tokens=event.input_tokens,
                        output_tokens=event.output_tokens,
                    )
                    # Metered separately from the transcript row above, so the
                    # daily budget survives the conversation being deleted.
                    await usage_service.record_tokens(
                        session,
                        user_id=tool_context.user_id,
                        tokens=(event.input_tokens or 0) + (event.output_tokens or 0),
                    )

                case ToolCall():
                    record = await transcript_service.add_tool_call(
                        session,
                        conversation_id=conversation_id,
                        tool_use_id=event.tool_use_id,
                        name=event.name,
                        tool_input=event.input,
                    )

                case ToolResult():
                    record = await transcript_service.add_tool_result(
                        session,
                        conversation_id=conversation_id,
                        tool_use_id=event.tool_use_id,
                        content=event.content,
                        is_error=event.is_error,
                        data=event.data,
                    )

                case StreamDone():
                    return TurnOutcome("succeeded")

                case StreamError():
                    return TurnOutcome(
                        "failed",
                        error=f"{event.code}: {event.message}",
                        retryable=event.code in RETRYABLE_ERROR_CODES,
                    )

            frame = event_frame(record)
            if frame is not None:
                await publish(session, channel, frame)

            # Every durable event is also a cancellation checkpoint. Stopping
            # here rather than mid-token means a tool call either happened or
            # did not — never half.
            # Note there is no shutdown check here, only a cancellation one.
            # Stopping immediately after persisting an assistant_message would
            # leave history ending on an assistant turn, which the next worker
            # cannot resume from. Shutdown is caught while tokens stream instead
            # — roughly once a second — which is before any row for the current
            # response exists.
            last_cancel_check = time.monotonic()
            reason = await task_service.stop_reason(session, task_id=task.id)
            if reason is not None:
                # Nothing to flush here either way: every durable row for this
                # turn is already written, which is what makes this a safe place
                # to stop at all.
                return TurnOutcome(reason)

        # The provider ended without a terminal event. Should not happen; if it
        # does, saying so beats reporting success.
        return TurnOutcome("failed", error="provider stream ended without a terminal event")
    finally:
        # Closing explicitly rather than leaving it to the garbage collector,
        # which would run the generator's cleanup on an arbitrary later loop.
        await stream.aclose()


async def name_conversation(
    conversation_id: uuid.UUID, history: list[ChatMessage], provider: LLMProvider
) -> None:
    """Name a conversation, on a session of its own, swallowing everything.

    Its own session because it runs concurrently with the turn, and one
    `AsyncSession` driven from two places at once is a corrupted connection
    rather than a race you can reason about.

    Swallowing everything because of where it is awaited: in a `finally` around
    the turn. An exception escaping here would replace whatever the turn was
    about to report — including, in the worst case, turning a successful answer
    into a failed task over a title.
    """
    try:
        async with SessionFactory() as session:
            await conversation_service.name_conversation(
                session, conversation_id=conversation_id, history=history, provider=provider
            )
    except Exception:
        logger.exception("naming conversation failed", conversation_id=str(conversation_id))


def already_answered(history: list[ChatMessage]) -> bool:
    """Does this conversation already end in an answer?

    Generation requires history to end on a user turn; every provider rejects a
    trailing assistant turn as a prefill. So this doubles as the resume guard
    and as the check that keeps a malformed request from ever being sent.
    """
    return bool(history) and history[-1].role == "assistant"
