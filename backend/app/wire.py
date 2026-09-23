"""The event vocabulary the browser folds, and the camelCase convention.

This is at the top level rather than under `api/` because **the browser receives
these shapes over two transports**. The REST and SSE responses come from
`api/routes/conversations.py`; the live frames come from `app/worker/turn.py`,
which publishes them on the bus while the turn is still running. One definition is
what lets a client fold a replayed event and a live one with the same function.
Two definitions is a bug that only appears after a refresh.

`api/schemas.py` is what is left once that is taken out: the response envelope,
the request bodies, and the resource shapes that genuinely only travel over
HTTP. It imports from here; nothing imports back.

**The wire is camelCase; Python is snake_case.** `ApiSchema` does the conversion
at the boundary, so no TypeScript file ever contains `created_at` and no Python
file ever contains `createdAt`. Everything on the wire inherits from it,
including the HTTP-only shapes next door.
"""

from datetime import datetime
from typing import Annotated, Any, Literal, TypedDict
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.models import EventRecord


class ApiSchema(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


# ------------------------------------------------------------------ events


class EventBase(ApiSchema):
    id: UUID
    # The replay cursor. A client that has seen up to `seq` asks the streaming
    # endpoint for everything after it, and gets exactly what it missed.
    seq: int
    created_at: datetime


class UserMessageOut(EventBase):
    type: Literal["user_message"] = "user_message"
    text: str


class AssistantMessageOut(EventBase):
    type: Literal["assistant_message"] = "assistant_message"
    text: str


class ToolCallOut(EventBase):
    type: Literal["tool_call"] = "tool_call"
    tool_use_id: str
    name: str
    input: dict[str, Any]


class ToolResultOut(EventBase):
    type: Literal["tool_result"] = "tool_result"
    tool_use_id: str
    content: str
    is_error: bool
    # The structured half of a result — aggregate rows, mostly — for a chart
    # to render from. `None` for every tool result that has nothing to plot.
    # Never parsed out of `content`; it travels beside it from ToolOutput.data.
    data: dict[str, Any] | None = None


# A discriminated union rather than one model with eight nullable fields. The
# generated OpenAPI schema is then honest about which fields exist together,
# and the TypeScript side gets a union it can `switch` on exhaustively.
AnyEventOut = UserMessageOut | AssistantMessageOut | ToolCallOut | ToolResultOut
EventOut = Annotated[AnyEventOut, Field(discriminator="type")]


class _CommonEventFields(TypedDict):
    """The three fields every event row contributes, whatever its type.

    A TypedDict rather than a plain dict so that `**common` below is checked
    field by field. As a `dict` it collapses to `dict[str, UUID | int |
    datetime]` and every unpack becomes an unverifiable union.
    """

    id: UUID
    seq: int
    created_at: datetime


def to_event_out(record: EventRecord) -> AnyEventOut | None:
    """One stored event as the browser should see it, or None to leave it out.

    This is the second of the two views the event log supports — `load_history`
    in `services/transcript_service.py` is the other. They are allowed to
    diverge, and this is where that divergence goes: hide an event from the
    user, summarize a noisy tool result, attach a cost. Do not let the two
    collapse back into one function just because they happen to agree today.
    """
    data = record.data
    common: _CommonEventFields = {
        "id": record.id,
        "seq": record.seq,
        "created_at": record.created_at,
    }

    match record.type:
        case "user_message":
            return UserMessageOut(text=data.get("text", ""), **common)
        case "assistant_message":
            # Empty when the response was nothing but a tool call. The row is
            # kept (it carries the token counts) but there is no bubble to draw.
            text = data.get("text", "")
            return AssistantMessageOut(text=text, **common) if text else None
        case "tool_call":
            return ToolCallOut(
                tool_use_id=data["tool_use_id"],
                name=data["name"],
                input=data.get("input", {}),
                **common,
            )
        case "tool_result":
            return ToolResultOut(
                tool_use_id=data["tool_use_id"],
                content=data.get("content", ""),
                is_error=data.get("is_error", False),
                data=data.get("data"),
                **common,
            )
        case _:
            return None


def event_frame(record: EventRecord) -> dict[str, Any] | None:
    """One durable event as a frame on the wire, or None if it is not shown.

    The same shape the REST endpoint returns, nested under an envelope so its
    own `type` does not collide with the frame's. Defined once here and used by
    both the route and the worker, which is the reason this module exists.
    """
    out = to_event_out(record)
    if out is None:
        return None
    return {"type": "event", "event": out.model_dump(by_alias=True, mode="json")}
