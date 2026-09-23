"""Provider-neutral conversation and stream types.

**This is the seam.** Nothing above this module knows which vendor produced a
token. Every provider adapter normalizes its own wire format into these types,
and the route, the service layer, and the frontend all speak only this
vocabulary.

The reason to do this on day one, before there is a second provider: swapping
models is not the only thing that breaks a naive design. Vendors change their
own event shapes between versions, and the moment a tool call or a thinking
block shows up you need somewhere to put it that isn't "whatever the SDK
happened to emit." Adding a case here is cheap; retrofitting the seam later
means touching every layer at once.

Adding an event type is a four-file change — this file, the adapter that emits
it, the SSE encoder in api/routes/conversations.py, and the TypeScript union in
frontend/src/api/stream.ts. Keep those four in step.
"""

from dataclasses import dataclass, field
from typing import Any, Literal

# --------------------------------------------------------------- history in
#
# What gets sent to the model. A turn is a LIST of blocks, not a string,
# because a single assistant turn can be "here is my reasoning, now run this
# tool" and a single user turn can be "here are the results of three tools."
# Flattening that to text is exactly the mistake that makes tools painful to
# retrofit.


@dataclass(frozen=True, slots=True)
class TextBlock:
    text: str


@dataclass(frozen=True, slots=True)
class ToolUseBlock:
    """The model asking for a tool to be run. Appears in an assistant turn."""

    tool_use_id: str
    name: str
    input: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolResultBlock:
    """The answer to a `ToolUseBlock`. Appears in the NEXT user turn.

    `tool_use_id` is load-bearing: the provider rejects history where a tool use
    has no matching result, or a result no matching use. Replay has to keep them
    paired even when a run died between the two — see `load_history`.
    """

    tool_use_id: str
    content: str
    is_error: bool = False


ContentBlock = TextBlock | ToolUseBlock | ToolResultBlock


@dataclass(frozen=True, slots=True)
class ChatMessage:
    """One turn of conversation history, as the model should see it."""

    role: Literal["user", "assistant"]
    content: list[ContentBlock]


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """A tool offered to the model.

    `input_schema` is JSON Schema. It must be a closed object — every property
    declared, `required` listed, `additionalProperties: false` — because the
    adapter sends these as strict tools, which is what lets a handler trust its
    input instead of re-validating it. See app/tools/base.py.
    """

    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolOutput:
    """What running a tool produced.

    Lives here rather than in app/tools so the provider contract can name it
    without the LLM layer importing the application's tools — the dependency
    runs one way, tools -> seam, and never back.

    `data` is the structured half of the result — aggregate rows, mostly —
    riding beside `content`, which stays the text the model reads. A chart is
    rendered from `data` in the browser and never from `content`, which is
    prose by the time it gets there. `None` for every tool result that has
    nothing to plot, which today is most of them.
    """

    content: str
    is_error: bool = False
    data: dict[str, Any] | None = None


# -------------------------------------------------------------- events out
#
# What comes back while a turn runs. These are yielded in order and are a
# superset of what reaches the browser: `AssistantMessage` exists so the caller
# can persist a row, and is not forwarded to the client, which already has that
# text from the deltas.


@dataclass(frozen=True, slots=True)
class TextDelta:
    """A fragment of the visible answer. For display only."""

    text: str


@dataclass(frozen=True, slots=True)
class ThinkingDelta:
    """A fragment of the model's summarized reasoning.

    Rendered differently from `TextDelta` and never persisted: reasoning is
    scaffolding for one turn, not part of the transcript. Replaying it as
    conversation history on a later turn is wrong — but replaying it *within*
    one turn, across a tool call, is required. The adapter handles that
    internally so nothing above the seam has to know about it.
    """

    text: str


@dataclass(frozen=True, slots=True)
class AssistantMessage:
    """One complete model response, ready to be written down.

    Emitted once per call to the provider — so a turn that calls two tools in
    sequence produces three of these. `text` is empty when the model's entire
    response was a tool call, which is normal and which replay skips.
    """

    text: str
    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class ToolCall:
    """The model asked for a tool. Emitted before the tool runs."""

    tool_use_id: str
    name: str
    input: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ToolResult:
    """What the tool returned. Emitted after it runs, before the next model call.

    `is_error` is not an exception: a tool that fails reports the failure back
    to the model, which is then free to fix its arguments and try again. Raising
    would end the turn and throw that recovery away.

    `data` carries `ToolOutput.data` through to the transcript. The model never
    sees it — only `content` goes into the wire-format sent back to the
    provider — it exists so the worker can persist it on the `tool_result` row
    for the browser to render a chart from.
    """

    tool_use_id: str
    content: str
    is_error: bool = False
    data: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class StreamDone:
    """Terminal success. Token counts are the whole turn, summed across every
    model call it took — the per-call numbers ride on `AssistantMessage`."""

    stop_reason: str | None
    input_tokens: int | None
    output_tokens: int | None


@dataclass(frozen=True, slots=True)
class StreamError:
    """Terminal failure, with a stable machine-readable `code`.

    A stable code is what lets the frontend decide whether to offer "retry"
    without string-matching an error message that changes between SDK versions.
    """

    code: Literal[
        "rate_limited",
        "auth_failed",
        "bad_request",
        "out_of_credit",
        "provider_unavailable",
        "connection_failed",
        "refused",
        "output_truncated",
        "tool_loop_exhausted",
        "internal_error",
    ]
    message: str


# Which failures are worth trying again, and which are the same answer twice.
#
# This is the point of a stable `code`: the worker decides whether to requeue a
# turn by set membership rather than by reading an error message that changes
# between SDK versions. A wrong key is wrong on every attempt; a 529 is not.
RETRYABLE_ERROR_CODES = frozenset(
    {
        "rate_limited",
        "provider_unavailable",
        "connection_failed",
        "internal_error",
    }
)


LLMStreamEvent = (
    TextDelta | ThinkingDelta | AssistantMessage | ToolCall | ToolResult | StreamDone | StreamError
)
