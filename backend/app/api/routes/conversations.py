"""Conversation endpoints.

The shape changed when generation moved to a worker, and the change is worth
naming: **sending a message and watching the answer are now two different
requests.** POST appends the message and enqueues work; GET /stream watches.

That looked like an extra round trip and is actually the point. One endpoint
watches, whether it was opened a millisecond after sending or by a browser that
refreshed halfway through — both say "I have seen up to `seq`, give me the
rest." Resuming is not a special case; it is the only case.
"""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from app.api.deps import CurrentUser, DbSession
from app.api.middleware import current_request_id
from app.api.schemas import (
    ApiResponse,
    ConversationDetailOut,
    ConversationOut,
    ConversationUpdateIn,
    SendMessageIn,
    SendMessageOut,
    TaskOut,
    to_conversation_detail,
)
from app.bus import bus, channel_for, publish
from app.db import SessionFactory
from app.logging import get_logger
from app.services import conversation_service, task_service, transcript_service, usage_service
from app.wire import event_frame

logger = get_logger(__name__)
router = APIRouter(prefix="/conversations", tags=["conversations"])

# How long to wait on a quiet stream before sending a comment frame. Two jobs:
# proxies and load balancers hang up on idle connections, and it is when we
# re-check whether the task ended without us hearing about it.
HEARTBEAT_SECONDS = 15


def _sse(payload: dict[str, Any]) -> str:
    """Encode one Server-Sent Event.

    The double newline is the frame delimiter — without it the browser buffers
    forever and the stream looks hung.
    """
    return f"data: {json.dumps(payload)}\n\n"


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_conversation(
    session: DbSession, user_id: CurrentUser
) -> ApiResponse[ConversationOut]:
    conversation = await conversation_service.create_conversation(session, user_id=user_id)
    return ApiResponse(data=ConversationOut.model_validate(conversation))


@router.get("")
async def list_conversations(
    session: DbSession,
    user_id: CurrentUser,
    # FBT002: a boolean default is a flag argument everywhere except here — a
    # FastAPI query parameter has to be declared as one, and `?archived=true`
    # is the URL this produces.
    archived: Annotated[  # noqa: FBT002
        bool, Query(description="Return the archive instead of the list.")
    ] = False,
) -> ApiResponse[list[ConversationOut]]:
    conversations = await conversation_service.list_conversations(
        session, user_id=user_id, archived=archived
    )
    return ApiResponse(data=[ConversationOut.model_validate(c) for c in conversations])


@router.get("/{conversation_id}")
async def get_conversation(
    conversation_id: uuid.UUID, session: DbSession, user_id: CurrentUser
) -> ApiResponse[ConversationDetailOut]:
    conversation = await conversation_service.get_conversation(
        session, conversation_id=conversation_id, user_id=user_id, with_events=True
    )
    if conversation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")

    # Returned alongside the transcript so a page that just loaded knows whether
    # to reattach to the stream or treat what it has as finished.
    active = await task_service.active_task(session, conversation_id=conversation_id)
    return ApiResponse(data=to_conversation_detail(conversation, active_task=active))


@router.patch("/{conversation_id}")
async def update_conversation(
    conversation_id: uuid.UUID,
    body: ConversationUpdateIn,
    session: DbSession,
    user_id: CurrentUser,
) -> ApiResponse[ConversationOut]:
    """Rename, pin, or archive. One endpoint because they are one resource.

    `model_fields_set` rather than a None check: the body is a patch, and a
    field that was not sent has to be distinguishable from one sent as null.
    Three endpoints would avoid that and cost the client three round trips to
    unarchive-and-unpin.
    """
    conversation = await conversation_service.get_conversation(
        session, conversation_id=conversation_id, user_id=user_id
    )
    if conversation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")

    sent = body.model_fields_set

    if "title" in sent:
        title = (body.title or "").strip()
        if not title:
            # Rejected rather than quietly restoring the auto title: the old one
            # is gone by then, and inventing a different name than the one the
            # user cleared is a worse surprise than an error message.
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Title cannot be empty")
        await conversation_service.rename_conversation(
            session, conversation=conversation, title=title
        )

    if "archived" in sent and body.archived is not None:
        await conversation_service.set_archived(
            session, conversation=conversation, archived=body.archived
        )

    # After archiving, so `{"archived": false, "pinned": true}` unarchives and
    # then pins rather than pinning something that is about to be unpinned.
    if "pinned" in sent and body.pinned is not None:
        await conversation_service.set_pinned(
            session, conversation=conversation, pinned=body.pinned
        )

    return ApiResponse(data=ConversationOut.model_validate(conversation))


@router.delete("/{conversation_id}")
async def delete_conversation(
    conversation_id: uuid.UUID, session: DbSession, user_id: CurrentUser
) -> ApiResponse[None]:
    """Delete a conversation and everything hanging off it.

    An enveloped 200 rather than a 204, because "every response is
    `{data, meta}`" is a rule the client depends on: `apiFetch` parses a body
    unconditionally, and one endpoint that sends none is a JSON error at the
    HTTP boundary rather than anywhere near this code.

    The task is superseded first, which narrows the window where a worker is
    mid-turn on a conversation that has stopped existing. It does not close it —
    the worker is what does that, and getting it wrong stopped the whole queue
    rather than one turn. See CONVENTIONS.md > Deleting one that is still answering.
    """
    conversation = await conversation_service.get_conversation(
        session, conversation_id=conversation_id, user_id=user_id
    )
    if conversation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")

    await task_service.supersede_active(session, conversation_id=conversation_id)
    await conversation_service.delete_conversation(session, conversation=conversation)
    return ApiResponse(data=None)


@router.post("/{conversation_id}/messages", status_code=status.HTTP_202_ACCEPTED)
async def send_message(
    conversation_id: uuid.UUID,
    body: SendMessageIn,
    session: DbSession,
    user_id: CurrentUser,
) -> ApiResponse[SendMessageOut]:
    """Append a message and queue the turn. Returns a receipt, not an answer."""
    content = body.content.strip()
    if not content:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Message cannot be empty")

    conversation = await conversation_service.get_conversation(
        session, conversation_id=conversation_id, user_id=user_id
    )
    if conversation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")

    # Before anything is written: a refused message should leave no trace in
    # the conversation, and must not supersede the turn that is running.
    refusal = await usage_service.refusal(session, user_id=user_id)
    if refusal is not None:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, refusal)

    # Talking to something brings it back. The alternative is a message that
    # succeeds into a conversation the sidebar does not list, which reads as
    # the app having lost it.
    if conversation.archived_at is not None:
        await conversation_service.set_archived(session, conversation=conversation, archived=False)

    # Before the new message is written, so the old turn cannot append to a
    # history that has changed underneath it.
    await task_service.supersede_active(session, conversation_id=conversation_id)

    record = await transcript_service.add_user_message(
        session, conversation=conversation, text=content
    )
    task = await task_service.enqueue(
        session,
        kind="chat_turn",
        conversation_id=conversation_id,
        # Carried onto the row so the worker can re-bind it. This is the only
        # thread tying the request that asked for a turn to the process that
        # ran it — they share no memory and no log stream.
        request_id=current_request_id(),
    )
    await usage_service.record_message(session, user_id=user_id)

    # For anyone already watching — a second tab, or another device.
    frame = event_frame(record)
    if frame is not None:
        await publish(session, channel_for(conversation_id), frame)

    logger.info(
        "turn queued",
        conversation_id=str(conversation_id),
        task_id=str(task.id),
        user_id=user_id,
    )
    return ApiResponse(data=SendMessageOut(task_id=task.id, seq=record.seq))


@router.post("/{conversation_id}/cancel")
async def cancel_turn(
    conversation_id: uuid.UUID, session: DbSession, user_id: CurrentUser
) -> ApiResponse[TaskOut | None]:
    """Ask the worker to stop.

    A request, not a command — the worker is another process and cannot be
    interrupted. It notices at the next event boundary, so cancelling mid
    sentence finishes the sentence. Everything written up to that point stays:
    a cancelled turn is a shorter turn, not a discarded one.
    """
    conversation = await conversation_service.get_conversation(
        session, conversation_id=conversation_id, user_id=user_id
    )
    if conversation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")

    task = await task_service.active_task(session, conversation_id=conversation_id)
    if task is None:
        return ApiResponse(data=None)

    await task_service.request_cancel(session, task=task)
    return ApiResponse(data=TaskOut.model_validate(task))


@router.get("/{conversation_id}/stream")
async def stream_conversation(
    conversation_id: uuid.UUID,
    session: DbSession,
    user_id: CurrentUser,
    since: Annotated[int, Query(ge=0, description="Highest event seq already seen.")] = 0,
) -> StreamingResponse:
    """Watch a conversation from `since` onwards.

    Used identically by a browser that just sent a message and one that
    refreshed mid-answer. Authorization happens here, before the response
    starts, because once the first byte is out the status code is spent.
    """
    conversation = await conversation_service.get_conversation(
        session, conversation_id=conversation_id, user_id=user_id
    )
    if conversation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")

    async def frames() -> AsyncIterator[str]:
        # Subscribe BEFORE replaying. Do it the other way around and anything
        # published between the query and the subscribe is gone — the one race
        # in this design that would be invisible in testing and obvious in use.
        async with bus.subscribe(channel_for(conversation_id)) as queue:
            cursor = since

            # A session of its own: the request-scoped one from Depends() is
            # torn down on a schedule that has nothing to do with how long this
            # generator lives.
            async with SessionFactory() as read:
                missed = await transcript_service.events_since(
                    read, conversation_id=conversation_id, since=since
                )
                for record in missed:
                    cursor = max(cursor, record.seq)
                    frame = event_frame(record)
                    if frame is not None:
                        yield _sse(frame)

                task = await task_service.active_task(read, conversation_id=conversation_id)

            if task is None:
                # Nothing running. The caller is caught up, so say so and hang
                # up rather than holding a connection open for no reason.
                yield _sse({"type": "status", "taskId": None, "status": "idle"})
                return

            task_id = task.id
            yield _sse({"type": "status", "taskId": str(task_id), "status": task.status})

            while True:
                try:
                    frame = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
                except TimeoutError:
                    # An SSE comment: keeps the connection alive without being
                    # an event the client has to understand.
                    yield ": keep-alive\n\n"

                    # The worker may have finished while we heard nothing —
                    # a dropped NOTIFY, or a task that died. The database is
                    # the authority, so ask it rather than wait forever.
                    async with SessionFactory() as read:
                        current = await task_service.get_task(read, task_id=task_id)
                    if current is None or current.status in task_service.TERMINAL_STATUSES:
                        final = current.status if current is not None else "failed"
                        yield _sse({"type": "status", "taskId": str(task_id), "status": final})
                        return
                    continue

                # Replay and live overlap by design, so drop what was already
                # sent. Cheaper and far more obvious than trying to make the
                # two halves meet exactly.
                if frame.get("type") == "event":
                    seq = frame["event"]["seq"]
                    if seq <= cursor:
                        continue
                    cursor = seq

                # A status frame for some OTHER task is not ours to report or to
                # end on, and one will arrive whenever a newer message
                # supersedes an older turn: the retired worker settles a second
                # or two later and publishes its own terminal status to the same
                # channel. Without this check that frame hangs up a stream that
                # is watching the turn which replaced it — the reader sees the
                # answer stop dead, and only a refetch and reattach brings it
                # back. Events are not filtered: the rows the old turn already
                # wrote are part of this conversation whoever produced them.
                if frame.get("type") == "status" and frame.get("taskId") != str(task_id):
                    continue

                yield _sse(frame)

                if (
                    frame.get("type") == "status"
                    and frame.get("status") in task_service.TERMINAL_STATUSES
                ):
                    return

    return StreamingResponse(
        frames(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # Tells nginx and friends not to buffer. Without it a proxy can hold
            # the whole response and deliver it at once, which looks exactly
            # like streaming being broken.
            "X-Accel-Buffering": "no",
        },
    )
