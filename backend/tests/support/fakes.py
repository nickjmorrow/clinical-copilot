"""A scripted LLM provider.

This file is the point of `LLMProvider` being a Protocol. Nothing here inherits
from anything or imports the Anthropic SDK; it satisfies the contract by shape,
and the assignment at the bottom is a static assertion that it still does. If
someone changes the seam, this stops type-checking — which is the cheapest
possible way to find out.
"""

import asyncio
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any

from app.llm.base import LLMProvider, ToolExecutor
from app.llm.types import (
    AssistantMessage,
    ChatMessage,
    LLMStreamEvent,
    StreamDone,
    StreamError,
    TextDelta,
    ThinkingDelta,
    ToolCall,
    ToolDefinition,
    ToolResult,
)


@dataclass(frozen=True)
class RunTool:
    """Script step: emit a ToolCall, really run it, emit the real result.

    Use this when the tool registry should be part of the test. Put literal
    ToolCall/ToolResult events in the script instead when it should not be.
    """

    tool_use_id: str
    name: str
    input: dict[str, Any] = field(default_factory=dict)


Step = LLMStreamEvent | RunTool


@dataclass
class FakeProvider:
    """Replays a fixed script and records what it was asked."""

    script: list[Step] = field(default_factory=list)
    delay: float = 0.0
    calls: list[dict[str, Any]] = field(default_factory=list)
    executed: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    closed: bool = False
    # What `complete` returns. None is the failure case, and it is the default
    # because it is the one every caller must already handle.
    completion: str | None = None
    completions: list[dict[str, str]] = field(default_factory=list)

    async def stream(
        self,
        *,
        system: str,
        messages: list[ChatMessage],
        tools: list[ToolDefinition],
        execute_tool: ToolExecutor,
    ) -> AsyncGenerator[LLMStreamEvent]:
        # Recorded so a test can assert what load_history actually handed the
        # model: the folded turns, the repaired orphans, which system prompt.
        self.calls.append({"system": system, "messages": messages, "tools": tools})
        try:
            for step in self.script:
                if self.delay:
                    await asyncio.sleep(self.delay)
                if isinstance(step, RunTool):
                    yield ToolCall(tool_use_id=step.tool_use_id, name=step.name, input=step.input)
                    self.executed.append((step.name, step.input))
                    output = await execute_tool(step.name, step.input)
                    yield ToolResult(
                        tool_use_id=step.tool_use_id,
                        content=output.content,
                        is_error=output.is_error,
                        data=output.data,
                    )
                else:
                    yield step
        finally:
            # Asserted by the worker test: the `finally: await stream.aclose()`
            # in _generate is load-bearing and trivially deletable.
            self.closed = True

    async def complete(self, *, system: str, prompt: str) -> str | None:
        self.completions.append({"system": system, "prompt": prompt})
        return self.completion


@dataclass
class HangingProvider:
    """Streams forever. For testing anything that has to stop a turn."""

    chunk: str = "token "
    delay: float = 0.01

    async def stream(
        self,
        *,
        system: str,
        messages: list[ChatMessage],
        tools: list[ToolDefinition],
        execute_tool: ToolExecutor,
    ) -> AsyncGenerator[LLMStreamEvent]:
        while True:
            await asyncio.sleep(self.delay)
            yield TextDelta(text=self.chunk)

    async def complete(self, *, system: str, prompt: str) -> str | None:
        return None


def says(text: str, *, chunks: int = 3) -> list[Step]:
    """The shape a real turn has: deltas, then the durable message, then done.

    The deltas and the AssistantMessage deliberately overlap — that is how the
    real adapter behaves, and the overlap is what the browser relies on to
    replace its token preview.
    """
    size = max(1, len(text) // chunks)
    parts = [text[i : i + size] for i in range(0, len(text), size)]
    return [
        ThinkingDelta(text="considering"),
        *[TextDelta(text=part) for part in parts],
        AssistantMessage(text=text, input_tokens=100, output_tokens=len(parts)),
        StreamDone(stop_reason="end_turn", input_tokens=100, output_tokens=len(parts)),
    ]


def calls_tool_then_says(
    *, tool: str, args: dict[str, Any], text: str, tool_use_id: str = "toolu_test_1"
) -> list[Step]:
    """A two-model-call turn.

    The empty AssistantMessage is not a mistake: a response that was nothing but
    a tool call really does produce one, it carries that call's token counts,
    and both `build_history` and `to_event_out` have to drop it.
    """
    return [
        AssistantMessage(text="", input_tokens=100, output_tokens=20),
        RunTool(tool_use_id=tool_use_id, name=tool, input=args),
        *says(text),
    ]


def fails(code: str = "rate_limited", message: str = "Rate limited.") -> list[Step]:
    return [TextDelta(text="par"), StreamError(code=code, message=message)]  # type: ignore[arg-type]


# Static conformance checks. No runtime cost; they fail type checking the moment
# the Protocol and these fakes disagree.
_conforms: LLMProvider = FakeProvider()
_also_conforms: LLMProvider = HangingProvider()
