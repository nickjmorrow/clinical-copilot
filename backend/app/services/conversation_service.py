"""The conversation row: creating one, listing them, and the four controls.

Routes stay thin: validate, authorize, call one of these, shape a response.
Everything a second caller would need — a CLI, a worker, a test — lives here.

Every function takes an explicit `session`. Reaching for a global or an ambient
request-scoped session is what makes service code untestable and unusable from
a background task.

The *contents* of a conversation are next door in `transcript_service.py`. The
split follows the one this codebase already makes in prose: a conversation is a
row with a title and four timestamps, and its transcript is an append-only log
that is replayed rather than read. They change for different reasons and are
queried by different callers.
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.llm.base import LLMProvider
from app.llm.types import ChatMessage, TextBlock
from app.logging import get_logger
from app.models import Conversation

logger = get_logger(__name__)

TITLE_MAX_LENGTH = 60

# What the namer is shown. The whole exchange is neither necessary nor free —
# the first message says what the conversation is about, and the answer is the
# part that can run to several thousand tokens on the cheap model's bill.
TITLE_PROMPT_MAX_LENGTH = 2_000


async def create_conversation(session: AsyncSession, *, user_id: str) -> Conversation:
    conversation = Conversation(user_id=user_id)
    session.add(conversation)
    await session.commit()
    await session.refresh(conversation)
    logger.info("conversation created", conversation_id=str(conversation.id), user_id=user_id)
    return conversation


async def list_conversations(
    session: AsyncSession, *, user_id: str, archived: bool = False
) -> list[Conversation]:
    """One user's conversations: pinned first, then newest.

    `archived` selects *between* the two piles rather than widening one. An
    archive you have to scroll past is not an archive, and a list that mixes
    them makes "where did it go" the first question every time.

    `nulls_last` is not decoration. In Postgres, DESC orders NULLs first by
    default, so without it every unpinned conversation sorts above every pinned
    one — exactly backwards, and only on a database with at least one pin.
    """
    archived_filter = (
        Conversation.archived_at.is_not(None) if archived else Conversation.archived_at.is_(None)
    )
    result = await session.execute(
        select(Conversation)
        .where(Conversation.user_id == user_id, archived_filter)
        .order_by(Conversation.pinned_at.desc().nulls_last(), Conversation.updated_at.desc())
    )
    return list(result.scalars().all())


async def get_conversation(
    session: AsyncSession,
    *,
    conversation_id: uuid.UUID,
    user_id: str,
    with_events: bool = False,
) -> Conversation | None:
    """Fetch one conversation.

    `user_id` is part of the WHERE clause, not an assertion afterwards: a
    conversation belonging to someone else must be indistinguishable from one
    that does not exist.
    """
    query = select(Conversation).where(
        Conversation.id == conversation_id,
        Conversation.user_id == user_id,
    )
    if with_events:
        # Eager-load: a lazy relationship access under asyncio raises rather
        # than quietly emitting a query, which is the correct behavior but a
        # confusing error if you forget this.
        query = query.options(selectinload(Conversation.events))

    result = await session.execute(query)
    return result.scalar_one_or_none()


async def owner_of(session: AsyncSession, *, conversation_id: uuid.UUID) -> str | None:
    """Who owns this conversation, without needing to already know.

    Deliberately NOT user-scoped, unlike `get_conversation` above, and the
    distinction matters. That function answers "may this user see this
    conversation", so the user id belongs in its WHERE clause. This one answers
    "whose conversation is this" — the question the worker asks, because it has
    no user in hand and is establishing identity rather than checking it.

    Only the worker should call this. A route that has a user already must use
    `get_conversation`, or it has turned an ownership check into a lookup.
    """
    return await session.scalar(
        select(Conversation.user_id).where(Conversation.id == conversation_id)
    )


# ------------------------------------------------------------------ controls
#
# Small functions rather than one `update_conversation(**fields)`. A keyword
# bag types as `Any` at every call site and lets a route pass a field nobody
# meant to be writable; three named verbs cannot.


async def rename_conversation(
    session: AsyncSession, *, conversation: Conversation, title: str
) -> Conversation:
    """Name it, and stop anything else renaming it.

    `title_custom` is the whole point of this being more than one assignment:
    the namer runs during the first turn, which can be after someone has
    already typed a name, and silently replacing it would be a bug nobody could
    reproduce on demand.
    """
    conversation.title = title
    conversation.title_custom = True
    await session.commit()
    await session.refresh(conversation)
    logger.info("conversation renamed", conversation_id=str(conversation.id))
    return conversation


async def set_pinned(
    session: AsyncSession, *, conversation: Conversation, pinned: bool
) -> Conversation:
    # Re-pinning an already-pinned conversation would otherwise move it to the
    # top of the pinned group, because `pinned_at` is the sort key.
    if pinned != (conversation.pinned_at is not None):
        conversation.pinned_at = datetime.now(UTC) if pinned else None
        await session.commit()
        await session.refresh(conversation)
    return conversation


async def set_archived(
    session: AsyncSession, *, conversation: Conversation, archived: bool
) -> Conversation:
    """Archiving also unpins.

    Otherwise a pin survives in a list nobody looks at, and unarchiving months
    later drops the conversation back at the top of the sidebar. Pinning is a
    statement about the working set; leaving the working set ends it.
    """
    if archived != (conversation.archived_at is not None):
        conversation.archived_at = datetime.now(UTC) if archived else None
        if archived:
            conversation.pinned_at = None
        await session.commit()
        await session.refresh(conversation)
    logger.info(
        "conversation archived" if archived else "conversation unarchived",
        conversation_id=str(conversation.id),
    )
    return conversation


async def delete_conversation(session: AsyncSession, *, conversation: Conversation) -> None:
    """Really gone: the row, its events, and its tasks.

    The cascade is declared on the foreign keys, so this is one statement and
    not three. Callers should settle any running task first — see the route —
    because a worker mid-turn on a deleted conversation will fail its next
    insert. `execute` in `worker/handlers.py` is what makes that survivable
    rather than fatal; settling first just means it usually does not happen.
    """
    conversation_id = conversation.id
    await session.execute(delete(Conversation).where(Conversation.id == conversation_id))
    await session.commit()
    logger.info("conversation deleted", conversation_id=str(conversation_id))


# ------------------------------------------------------------------ naming


def _clean_title(raw: str) -> str | None:
    """A model's answer as a title, or None if it did not give one.

    Everything here is a failure mode that has a name. Models wrap short
    answers in quotes; they add a trailing period to something that is not a
    sentence; and asked for one line they occasionally send two with the title
    on the first. None of that is worth a retry, and all of it is worth
    removing before it reaches a sidebar.
    """
    first_line = next((line for line in raw.splitlines() if line.strip()), "")
    title = first_line.strip().strip("\"“”'").rstrip(".").strip()
    return title[:TITLE_MAX_LENGTH] or None


def _title_transcript(history: Sequence[ChatMessage]) -> str:
    """The exchange as flat text for the namer.

    Text blocks only. A tool call's arguments are noise to a titler, and the
    blocks are provider-neutral here precisely so a second reader of the same
    history does not have to care how they were stored.
    """
    lines: list[str] = []
    for message in history:
        text = " ".join(b.text for b in message.content if isinstance(b, TextBlock)).strip()
        if text:
            lines.append(f"{message.role}: {text}")
    return "\n\n".join(lines)[:TITLE_PROMPT_MAX_LENGTH]


async def name_conversation(
    session: AsyncSession,
    *,
    conversation_id: uuid.UUID,
    history: Sequence[ChatMessage],
    provider: LLMProvider,
) -> str | None:
    """Replace the provisional title with one the model wrote.

    Called once per conversation, from the worker, for the first turn only. Not
    on every turn: a title that rewrites itself while you are talking is worse
    than a slightly general one, and the opening message is what a name is for.

    `history` is passed in rather than read here because the caller already has
    it — and because this runs *beside* that turn's generation on its own
    session, where re-reading would be a second query for the same rows.

    Returns the new title, or None if nothing changed. A failure is not an
    error: the truncated first message is already in `title` and is a
    serviceable name. That is what makes a blocking provider call acceptable
    here at all — there is nothing to retry and nobody to tell.
    """
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None or conversation.title_custom:
        return None

    transcript = _title_transcript(history)
    if not transcript:
        return None

    title = await provider.complete(system=settings.title_system_prompt, prompt=transcript)
    if title is None:
        return None

    cleaned = _clean_title(title)
    if cleaned is None:
        return None

    # Re-read rather than trusting the instance: naming takes a round trip to a
    # provider, and a rename can land inside it.
    await session.refresh(conversation)
    if conversation.title_custom:
        return None

    conversation.title = cleaned
    await session.commit()
    logger.info("conversation named", conversation_id=str(conversation.id))
    return cleaned
