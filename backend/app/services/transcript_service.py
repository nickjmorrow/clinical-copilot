"""The transcript: the append-only event log, and the two ways it is read back.

**Nothing here updates a row.** One record per user message, assistant response,
tool call and tool result, ordered by `seq`, and everything anyone reads is
*derived* by replaying them. The alternative — one row per turn holding the
final text — is right for plain chat and wrong the moment a tool is involved,
because a turn stops being one string and becomes some text, a call, a result,
and then more text.

`build_history` here is one of the two views the log supports; `to_event_out` in
`app/wire.py` is the other. The model's view folds consecutive same-speaker
events and repairs orphaned tool calls; the user's view hides the empty rows a
pure tool call produces. They are allowed to differ — that is the point, not an
accident — so do not collapse them back into one function because they happen
to agree today.

Every function takes an explicit `session`, for the reason given in
`conversation_service.py`.
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.types import ChatMessage, ContentBlock, TextBlock, ToolResultBlock, ToolUseBlock
from app.logging import get_logger
from app.models import Conversation, EventRecord

# The one thing this module borrows from its sibling, and it only goes this
# direction: a user message sets the provisional title, which is a fact about
# the conversation row. `conversation_service` imports nothing from here.
from app.services.conversation_service import TITLE_MAX_LENGTH

# Who a replayed block belongs to — `ChatMessage.role`, named once.
Speaker = Literal["user", "assistant"]

logger = get_logger(__name__)

# What a tool call gets told when its result was never written down. See
# `load_history` for when that happens and why it is repaired rather than
# dropped.
INTERRUPTED_TOOL_RESULT = "This tool call was interrupted and never completed."


# ------------------------------------------------------------------ writing
#
# One function per event type rather than one generic `append(type, data)`.
# The shapes in db/schema.sql are then constructed in exactly one place each,
# and a caller cannot invent a fifth event type by passing a string.


async def _append(
    session: AsyncSession,
    *,
    conversation_id: uuid.UUID,
    # A002: shadows the builtin, and is still the right name — it is the
    # `event_records.type` column, and renaming it here would make the service
    # and the schema disagree.
    type: str,  # noqa: A002
    data: dict[str, Any],
    input_tokens: int | None = None,
    output_tokens: int | None = None,
) -> EventRecord:
    record = EventRecord(
        conversation_id=conversation_id,
        type=type,
        data=data,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
    session.add(record)
    # Committed one at a time, on purpose. Each event is durable the moment it
    # happens, so a run that dies halfway leaves the first half on disk instead
    # of nothing. That is most of the value of writing events down at all.
    await session.commit()
    await session.refresh(record)
    return record


async def add_user_message(
    session: AsyncSession, *, conversation: Conversation, text: str
) -> EventRecord:
    # The first user message names the conversation *provisionally*, so the
    # sidebar has something to show before the turn is over. `name_conversation`
    # replaces it with a real title during the turn — which is a round trip to a
    # provider away, and far too long to show nothing.
    if conversation.title is None:
        conversation.title = text[:TITLE_MAX_LENGTH].strip() or "Untitled"

    # What makes the list's "newest first" mean newest *activity*. Nothing else
    # touches this column — there is deliberately no `onupdate=now()` on it,
    # because that fires for a pin and a rename too, and reordering the sidebar
    # because someone fixed a typo in a title is not what the ordering is for.
    conversation.updated_at = datetime.now(UTC)

    return await _append(
        session,
        conversation_id=conversation.id,
        type="user_message",
        data={"text": text},
    )


async def add_assistant_message(
    session: AsyncSession,
    *,
    conversation_id: uuid.UUID,
    text: str,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
) -> EventRecord:
    return await _append(
        session,
        conversation_id=conversation_id,
        type="assistant_message",
        data={"text": text},
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


async def add_tool_call(
    session: AsyncSession,
    *,
    conversation_id: uuid.UUID,
    tool_use_id: str,
    name: str,
    tool_input: dict[str, Any],
) -> EventRecord:
    return await _append(
        session,
        conversation_id=conversation_id,
        type="tool_call",
        data={"tool_use_id": tool_use_id, "name": name, "input": tool_input},
    )


async def add_tool_result(
    session: AsyncSession,
    *,
    conversation_id: uuid.UUID,
    tool_use_id: str,
    content: str,
    is_error: bool,
    data: dict[str, Any] | None = None,
) -> EventRecord:
    # `data` rides beside `content` under its own key rather than flattened
    # into this dict, so `to_event_out` can hand it to the browser untouched —
    # aggregate rows for a chart, never parsed back out of the rendered text.
    return await _append(
        session,
        conversation_id=conversation_id,
        type="tool_result",
        data={"tool_use_id": tool_use_id, "content": content, "is_error": is_error, "data": data},
    )


async def events_since(
    session: AsyncSession, *, conversation_id: uuid.UUID, since: int
) -> list[EventRecord]:
    """Everything that happened after `since`, oldest first.

    The replay half of resuming a stream. A browser that was showing this
    conversation up to some point asks for the rest, and `seq` being a plain
    monotonic integer is what makes that a single indexed range scan rather than
    a diff.
    """
    result = await session.execute(
        select(EventRecord)
        .where(EventRecord.conversation_id == conversation_id, EventRecord.seq > since)
        .order_by(EventRecord.seq)
    )
    return list(result.scalars().all())


# ------------------------------------------------------------------ replay


def _replay_block(record: EventRecord) -> tuple[Speaker, ContentBlock] | None:
    """One stored event as the model should see it, or None to leave it out."""
    data = record.data

    match record.type:
        case "user_message":
            text = data.get("text", "")
            return ("user", TextBlock(text=text)) if text else None
        case "assistant_message":
            # Empty when the model's whole response was a tool call. An empty
            # text block is a request validation error, so it is dropped — the
            # row still exists for the audit trail and for its token counts.
            text = data.get("text", "")
            return ("assistant", TextBlock(text=text)) if text else None
        case "tool_call":
            return (
                "assistant",
                ToolUseBlock(
                    tool_use_id=data["tool_use_id"],
                    name=data["name"],
                    input=data.get("input", {}),
                ),
            )
        case "tool_result":
            return (
                "user",
                ToolResultBlock(
                    tool_use_id=data["tool_use_id"],
                    content=data.get("content", ""),
                    is_error=data.get("is_error", False),
                ),
            )
        case _:
            logger.warning("unknown event type in replay", event_type=record.type)
            return None


async def load_history(session: AsyncSession, *, conversation_id: uuid.UUID) -> list[ChatMessage]:
    """Read a conversation's events and replay them into model-facing history.

    The reading is here; the thinking is in `build_history`, which is pure. That
    split is deliberate: the fold-and-repair logic below is the most intricate
    code in this codebase and the most expensive to get wrong, and a pure
    function is one you can test exhaustively in milliseconds without a database
    anywhere near it.
    """
    result = await session.execute(
        select(EventRecord)
        .where(EventRecord.conversation_id == conversation_id)
        .order_by(EventRecord.seq)
    )
    return build_history(list(result.scalars().all()))


def build_history(records: Sequence[EventRecord]) -> list[ChatMessage]:
    """Replay stored events into the turns a provider will accept.

    Three things happen here, and all three are the reason the table is an event
    log instead of a messages list:

    1. **Translation.** ORM rows in, provider-neutral blocks out. The LLM layer
       never sees a SQLAlchemy object, which is what keeps it testable without a
       database.

    2. **Folding.** Consecutive events with the same speaker become one turn.
       "Some text, then a tool call" is one assistant message; three tool
       results are one user message. The provider requires this, and doing it
       here means nothing upstream has to think about it.

    3. **Repair.** A run that died between calling a tool and recording the
       result leaves a tool call with no answer — and history in that state is
       rejected outright, which would wedge the conversation permanently. Every
       orphan gets a synthetic error result instead. The model reads it, sees
       what was interrupted, and carries on.

    This is also where context strategy will eventually live — truncation,
    summarization, dropping old tool noise. Today it replays everything, which
    is correct until a conversation outgrows the context window.
    """
    answered = {
        r.data["tool_use_id"]
        for r in records
        if r.type == "tool_result" and "tool_use_id" in r.data
    }

    # Pass 1: rows to (speaker, block), with orphaned tool calls answered.
    pairs: list[tuple[Speaker, ContentBlock]] = []
    orphans: list[str] = []
    repaired = 0
    for record in records:
        pair = _replay_block(record)
        if pair is None:
            continue
        role, block = pair

        # Flush before the speaker changes, so the synthetic results land in
        # the user turn immediately after the assistant turn that asked for
        # them — merging with any real results that did get written.
        if role != "assistant" and orphans:
            pairs.extend(
                (
                    "user",
                    ToolResultBlock(
                        tool_use_id=orphan, content=INTERRUPTED_TOOL_RESULT, is_error=True
                    ),
                )
                for orphan in orphans
            )
            orphans = []

        if isinstance(block, ToolUseBlock) and block.tool_use_id not in answered:
            orphans.append(block.tool_use_id)
            repaired += 1

        pairs.append((role, block))

    pairs.extend(
        ("user", ToolResultBlock(tool_use_id=o, content=INTERRUPTED_TOOL_RESULT, is_error=True))
        for o in orphans
    )

    if repaired:
        logger.info("repaired interrupted tool calls", count=repaired)

    # Pass 2: fold consecutive same-speaker blocks into turns.
    messages: list[ChatMessage] = []
    for role, block in pairs:
        if messages and messages[-1].role == role:
            messages[-1].content.append(block)
        else:
            messages.append(ChatMessage(role=role, content=[block]))

    return messages
