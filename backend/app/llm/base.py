"""The provider contract.

A Protocol rather than an ABC, so a test fake satisfies it structurally without
importing anything. That matters more than it sounds: it means you can develop
the whole request path against a scripted provider that emits a fixed sequence
of deltas, with no API key and no network.
"""

from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import Any, Protocol

from app.llm.types import ChatMessage, LLMStreamEvent, ToolDefinition, ToolOutput

# Run one tool and come back with its output. Passed in rather than imported,
# so the adapter drives the tool loop without knowing what any tool does.
#
# It must not raise: a tool that fails returns `ToolOutput(..., is_error=True)`
# so the model can read the failure and try again. An exception would end the
# turn instead, which is a much worse outcome for a typo in an argument.
ToolExecutor = Callable[[str, dict[str, Any]], Awaitable[ToolOutput]]


class LLMProvider(Protocol):
    """One model backend.

    Implementations must never raise for a provider-side failure — they yield a
    terminal `StreamError` instead. By the time a stream has started, HTTP
    headers are already sent and an exception cannot become a status code, so
    the error has to travel in-band as an event. Keeping that rule inside the
    adapter means every caller handles failure the same way.

    The adapter owns the tool loop (call the model, run what it asks for, call
    it again) for two reasons. It is the only layer allowed to touch raw SDK
    content blocks, and feeding those blocks back verbatim is what preserves
    thinking across a tool call. And it keeps the caller's job unchanged whether
    a turn took one model call or five: consume events until a terminal one.
    """

    def stream(
        self,
        *,
        system: str,
        messages: list[ChatMessage],
        tools: list[ToolDefinition],
        execute_tool: ToolExecutor,
    ) -> AsyncGenerator[LLMStreamEvent]:
        """Yield events until a terminal one.

        An `AsyncGenerator`, not merely an `AsyncIterator`: the caller stops
        consuming early — on cancellation, on shutdown — and must be able to
        `aclose()` the stream so the adapter runs its cleanup on the loop that
        owns it, rather than whenever the garbage collector gets to it. A plain
        iterator has no `aclose`, so an implementation that returned one would
        pass type checking and then fail at runtime in the caller's `finally`.
        """
        ...

    async def complete(self, *, system: str, prompt: str) -> str | None:
        """One short answer. No tools, no streaming, no thinking.

        A second method rather than options on `stream`, because this is a
        different kind of call and not the same one configured differently:
        nobody is watching it, there is no turn to resume or cancel, and it runs
        on the cheap model. Naming a conversation is the only caller today;
        anything else that wants a sentence out of a model rather than a
        conversation belongs here too.

        `None` means it did not work, and the same rule applies as to `stream`:
        **never raise for a provider failure.** Every caller is doing something
        optional — that is what makes a non-streaming call acceptable at all —
        so a failure has to be a value it can ignore rather than an exception
        that takes down whatever it was decorating.
        """
        ...
