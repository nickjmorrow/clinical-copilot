"""Pinning, archiving, renaming, and the title the model writes.

Every one of these is a small function; what is worth testing is the
interaction between them, because that is where the bugs are. Archiving unpins.
A rename beats the namer no matter which finishes first. The list is two lists.
"""

import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import dataclass

import pytest

from app.db import SessionFactory
from app.llm.base import LLMProvider, ToolExecutor
from app.llm.types import (
    AssistantMessage,
    ChatMessage,
    LLMStreamEvent,
    StreamDone,
    TextDelta,
    ToolDefinition,
)
from app.models import Conversation
from app.services import conversation_service, task_service, transcript_service
from app.worker import loop
from tests.support.fakes import FakeProvider, says


@dataclass
class DeletingProvider:
    """Streams a turn, and lets the test pull the conversation out from under it.

    `when` picks which of the two failure modes this reproduces, and they are
    genuinely different code paths:

    * `"mid_stream"` deletes before the assistant message is written, so the
      worker's next INSERT violates a foreign key and the session is left
      needing a rollback;
    * `"before_done"` deletes after it, so **nothing fails during the turn at
      all** — the turn succeeds, and the only thing left that touches a row
      which no longer exists is settling the task.

    A fake here rather than in `support/fakes.py`: it exists to reproduce one
    defect, and the shared fakes are the vocabulary every other test reads.
    """

    on_delete: Callable[[], Awaitable[None]]
    when: str = "mid_stream"

    async def stream(
        self,
        *,
        system: str,
        messages: list[ChatMessage],
        tools: list[ToolDefinition],
        execute_tool: ToolExecutor,
    ) -> AsyncGenerator[LLMStreamEvent]:
        yield TextDelta(text="wor")
        if self.when == "mid_stream":
            await self.on_delete()
            # A committed delete is not visible to a session already inside a
            # transaction, so give the worker a beat to start a new one.
            await asyncio.sleep(0.05)
        yield TextDelta(text="king")
        yield AssistantMessage(text="working", input_tokens=1, output_tokens=1)
        if self.when == "before_done":
            await self.on_delete()
            await asyncio.sleep(0.05)
        yield StreamDone(stop_reason="end_turn", input_tokens=1, output_tokens=1)

    async def complete(self, *, system: str, prompt: str) -> str | None:
        return None


_conforms: LLMProvider = DeletingProvider(on_delete=lambda: asyncio.sleep(0))


@pytest.fixture
async def conversation(session):
    return await conversation_service.create_conversation(session, user_id="dev-user")


# ------------------------------------------------------------------ ordering


async def test_pinned_conversations_sort_above_newer_unpinned_ones(session):
    old = await conversation_service.create_conversation(session, user_id="dev-user")
    new = await conversation_service.create_conversation(session, user_id="dev-user")

    # Newest first, until something is pinned.
    listed = await conversation_service.list_conversations(session, user_id="dev-user")
    assert [c.id for c in listed] == [new.id, old.id]

    await conversation_service.set_pinned(session, conversation=old, pinned=True)

    # The regression this guards is specific: Postgres sorts NULLs FIRST under
    # DESC, so without `nulls_last` the pinned row lands at the bottom and the
    # bug only appears once somebody pins something.
    listed = await conversation_service.list_conversations(session, user_id="dev-user")
    assert [c.id for c in listed] == [old.id, new.id]


async def test_pinning_an_already_pinned_conversation_does_not_reorder_it(session):
    first = await conversation_service.create_conversation(session, user_id="dev-user")
    second = await conversation_service.create_conversation(session, user_id="dev-user")
    await conversation_service.set_pinned(session, conversation=first, pinned=True)
    await conversation_service.set_pinned(session, conversation=second, pinned=True)

    # second was pinned last, so it is first among the pinned.
    assert [
        c.id for c in await conversation_service.list_conversations(session, user_id="dev-user")
    ] == [
        second.id,
        first.id,
    ]

    pinned_at = first.pinned_at
    await conversation_service.set_pinned(session, conversation=first, pinned=True)
    assert first.pinned_at == pinned_at


# ------------------------------------------------------------------ archiving


async def test_archiving_removes_it_from_the_list_and_puts_it_in_the_archive(session, conversation):
    await conversation_service.set_archived(session, conversation=conversation, archived=True)

    assert await conversation_service.list_conversations(session, user_id="dev-user") == []
    archived = await conversation_service.list_conversations(
        session, user_id="dev-user", archived=True
    )
    assert [c.id for c in archived] == [conversation.id]


async def test_archiving_unpins(session, conversation):
    await conversation_service.set_pinned(session, conversation=conversation, pinned=True)
    await conversation_service.set_archived(session, conversation=conversation, archived=True)

    assert conversation.pinned_at is None

    # And unarchiving does not bring the pin back — it returns to the list, not
    # to the top of it.
    await conversation_service.set_archived(session, conversation=conversation, archived=False)
    assert conversation.pinned_at is None
    assert conversation.archived_at is None


async def test_deleting_takes_the_transcript_with_it(session, conversation):
    await transcript_service.add_user_message(session, conversation=conversation, text="hi")
    conversation_id = conversation.id

    await conversation_service.delete_conversation(session, conversation=conversation)

    assert await conversation_service.list_conversations(session, user_id="dev-user") == []
    # Cascade, declared on the foreign key rather than done in three statements.
    assert (
        await transcript_service.events_since(session, conversation_id=conversation_id, since=0)
        == []
    )


# ------------------------------------------------------------------ naming


async def test_the_first_turn_names_the_conversation(session, conversation):
    await transcript_service.add_user_message(
        session, conversation=conversation, text="how do I make sourdough starter from scratch"
    )
    await task_service.enqueue(session, kind="chat_turn", conversation_id=conversation.id)

    # The provisional title until the namer lands: the message, truncated.
    assert conversation.title == "how do I make sourdough starter from scratch"

    provider = FakeProvider(says("Flour and water."), completion="Sourdough Starter")
    assert await loop.drain("test-worker", provider=provider) == 1

    await session.refresh(conversation)
    assert conversation.title == "Sourdough Starter"
    assert conversation.title_custom is False

    # Named from the opening message, not from the answer — which is why it can
    # run beside generation instead of after it.
    assert len(provider.completions) == 1
    assert "sourdough starter" in provider.completions[0]["prompt"]
    assert "Flour and water" not in provider.completions[0]["prompt"]


async def test_a_second_turn_does_not_rename(session, conversation):
    await transcript_service.add_user_message(session, conversation=conversation, text="hello")
    await task_service.enqueue(session, kind="chat_turn", conversation_id=conversation.id)
    await loop.drain("test-worker", provider=FakeProvider(says("Hi."), completion="A Greeting"))

    await transcript_service.add_user_message(session, conversation=conversation, text="and now")
    await task_service.enqueue(session, kind="chat_turn", conversation_id=conversation.id)
    provider = FakeProvider(says("Still here."), completion="Something Else")
    await loop.drain("test-worker", provider=provider)

    await session.refresh(conversation)
    assert conversation.title == "A Greeting"
    # Not called at all, rather than called and ignored: a title per turn is a
    # provider call per turn for a value that is thrown away.
    assert provider.completions == []


async def test_a_rename_wins_over_the_namer(session, conversation):
    await transcript_service.add_user_message(session, conversation=conversation, text="hello")
    await task_service.enqueue(session, kind="chat_turn", conversation_id=conversation.id)

    await conversation_service.rename_conversation(session, conversation=conversation, title="Mine")
    await loop.drain("test-worker", provider=FakeProvider(says("Hi."), completion="Not Mine"))

    await session.refresh(conversation)
    assert conversation.title == "Mine"


async def test_a_failed_naming_call_keeps_the_provisional_title_and_the_turn(session, conversation):
    await transcript_service.add_user_message(
        session, conversation=conversation, text="what is the airspeed of a swallow"
    )
    task = await task_service.enqueue(session, kind="chat_turn", conversation_id=conversation.id)

    # `completion=None` is the default, and it is the provider failing.
    await loop.drain("test-worker", provider=FakeProvider(says("African or European?")))

    await session.refresh(task)
    await session.refresh(conversation)
    assert task.status == "succeeded"
    assert conversation.title == "what is the airspeed of a swallow"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('"Sourdough Starter"', "Sourdough Starter"),
        ("Sourdough Starter.", "Sourdough Starter"),
        ("Sourdough Starter\nHere is your title", "Sourdough Starter"),
        ("\n\n  Sourdough Starter  \n", "Sourdough Starter"),
        ("   ", None),
        ("x" * 200, "x" * conversation_service.TITLE_MAX_LENGTH),
    ],
)
def test_clean_title_strips_what_models_actually_add(raw, expected):
    assert conversation_service._clean_title(raw) == expected


# --------------------------------------------------- deleted mid-turn


@pytest.mark.parametrize("when", ["mid_stream", "before_done"])
async def test_deleting_a_conversation_mid_turn_does_not_wedge_the_worker(session, when):
    """The whole queue used to stop on this, and it is easy to reach.

    Delete removes the conversation and the cascade takes its events and its
    task row with it, while a worker is inside the turn. It wedged the worker
    twice, for two unrelated reasons, and both are worth keeping a test for:

    1. The next event written hits a foreign key that no longer resolves. That
       leaves the session needing a rollback — and the handler's own
       `logger.exception(..., task_id=str(task.id))` then lazy-loaded an
       expired attribute, which is a statement, which raised from *inside the
       logging call*.
    2. With the rollback in place, settling the task still UPDATEd a row that
       was gone. The existence check that was supposed to prevent that used
       `session.get`, which answered from the identity map without asking
       Postgres — so it reported the deleted row as present.

    Both escaped the `except` whose entire job is to keep one bad turn from
    taking the queue down with it, and the worker claimed nothing ever again.
    """
    doomed = await conversation_service.create_conversation(session, user_id="dev-user")
    await transcript_service.add_user_message(session, conversation=doomed, text="hello")
    await task_service.enqueue(session, kind="chat_turn", conversation_id=doomed.id)

    # Deleted from another session, as a second request really would.
    async def delete_it() -> None:
        async with SessionFactory() as other:
            conversation = await other.get(Conversation, doomed.id)
            assert conversation is not None
            await conversation_service.delete_conversation(other, conversation=conversation)

    await loop.drain("test-worker", provider=DeletingProvider(on_delete=delete_it, when=when))

    # The point of the test: the worker is still working. A second, healthy
    # conversation drains normally afterwards.
    survivor = await conversation_service.create_conversation(session, user_id="dev-user")
    await transcript_service.add_user_message(session, conversation=survivor, text="still here?")
    task = await task_service.enqueue(session, kind="chat_turn", conversation_id=survivor.id)

    assert await loop.drain("test-worker", provider=FakeProvider(says("Yes."))) == 1
    await session.refresh(task)
    assert task.status == "succeeded"
