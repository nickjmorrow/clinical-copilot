"""Anthropic adapter — the only file in the codebase that imports `anthropic`.

If you find yourself importing the SDK anywhere else, the seam has leaked.
"""

from collections.abc import AsyncGenerator, Iterable
from typing import TYPE_CHECKING, Any, cast

import anthropic

from app.config import settings
from app.llm.base import ToolExecutor
from app.llm.types import (
    AssistantMessage,
    ChatMessage,
    ContentBlock,
    LLMStreamEvent,
    StreamDone,
    StreamError,
    TextBlock,
    TextDelta,
    ThinkingDelta,
    ToolCall,
    ToolDefinition,
    ToolResult,
    ToolResultBlock,
    ToolUseBlock,
)
from app.logging import get_logger

if TYPE_CHECKING:
    from anthropic.types import MessageParam

logger = get_logger(__name__)

# A 5xx from the provider is "come back later"; a 4xx is "you sent something
# wrong". They become different StreamError codes, so the boundary is named.
_SERVER_ERROR_STATUS = 500


def _wire_block(block: ContentBlock) -> dict[str, Any]:
    match block:
        case TextBlock():
            return {"type": "text", "text": block.text}
        case ToolUseBlock():
            return {
                "type": "tool_use",
                "id": block.tool_use_id,
                "name": block.name,
                "input": block.input,
            }
        case ToolResultBlock():
            return {
                "type": "tool_result",
                "tool_use_id": block.tool_use_id,
                "content": block.content,
                "is_error": block.is_error,
            }


def _wire_tool(tool: ToolDefinition) -> dict[str, Any]:
    return {
        "name": tool.name,
        "description": tool.description,
        "input_schema": tool.input_schema,
        # Strict: the provider guarantees the arguments validate against the
        # schema before they are ever sent. That is what lets a handler read
        # its input directly instead of defending against every field being
        # missing or the wrong type. It requires the closed schema documented
        # in app/tools/base.py.
        "strict": True,
    }


class AnthropicProvider:
    """Streams Claude responses as provider-neutral events, running whatever
    tools the model asks for along the way."""

    def __init__(self) -> None:
        # Checked here, at the one place that needs it, rather than by a
        # validator on Settings — that would refuse to start the API and the
        # migration step over a key neither of them uses. The worker builds this
        # at import, so a missing key still fails the worker at startup rather
        # than mid-request, with a message that says what to do.
        if not settings.anthropic_api_key.strip():
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your key."
            )

        # Explicit key from Settings rather than letting the SDK read the env
        # itself, so configuration stays in one place.
        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    async def stream(
        self,
        *,
        system: str,
        messages: list[ChatMessage],
        tools: list[ToolDefinition],
        execute_tool: ToolExecutor,
    ) -> AsyncGenerator[LLMStreamEvent]:
        """One conversational turn, which may take several calls to the model.

        The loop is: ask the model, stream what it says, run any tools it asked
        for, ask again with the results. It ends when the model answers without
        calling a tool — or when something terminal happens, which always
        arrives as a `StreamError` event rather than an exception.
        """
        # Everything except `messages` is identical on every call in the turn.
        # Keeping it that way is not just tidiness: `tools` and `system` are the
        # front of the prompt, and any change to them invalidates the cached
        # prefix for the rest of the conversation.
        request: dict[str, Any] = {
            "model": settings.anthropic_model,
            "max_tokens": settings.anthropic_max_tokens,
            "system": system,
            # Adaptive thinking: the model decides how much to reason.
            # `display: summarized` is opt-in — the default returns thinking
            # blocks with empty text, which looks like a long silent pause
            # in a streaming UI.
            "thinking": {"type": "adaptive", "display": "summarized"},
        }
        if tools:
            # Omitted rather than sent empty: an empty tool list is a request
            # validation error, not "no tools".
            request["tools"] = [_wire_tool(t) for t in tools]

        wire_messages: list[dict[str, Any]] = [
            {"role": m.role, "content": [_wire_block(b) for b in m.content]} for m in messages
        ]

        total_input = 0
        total_output = 0

        logger.info(
            "llm stream started",
            model=settings.anthropic_model,
            message_count=len(messages),
            tool_count=len(tools),
        )

        try:
            for iteration in range(settings.max_tool_iterations):
                async with self._client.messages.stream(
                    # The SDK types `messages` as its own TypedDicts. These
                    # dicts are valid MessageParams by construction — every one
                    # comes from _wire_block, over a closed union — but a plain
                    # dict is not assignable to a TypedDict, and building the
                    # SDK's types directly would drag its vocabulary across the
                    # seam this file exists to hold.
                    messages=cast("Iterable[MessageParam]", wire_messages),
                    **request,
                ) as stream:
                    async for event in stream:
                        if event.type == "content_block_delta":
                            if event.delta.type == "text_delta":
                                yield TextDelta(text=event.delta.text)
                            elif event.delta.type == "thinking_delta":
                                yield ThinkingDelta(text=event.delta.thinking)

                    final = await stream.get_final_message()

                # Billed per call, so the turn's cost is the sum even though the
                # same prefix is re-sent each time. That is the number you want
                # when you ask what a tool loop cost you.
                total_input += final.usage.input_tokens or 0
                total_output += final.usage.output_tokens or 0

                # A refusal is a successful HTTP response with nothing usable in
                # it, so it has to be checked explicitly — it will not raise.
                if final.stop_reason == "refusal":
                    logger.info("llm refused", model=settings.anthropic_model)
                    yield StreamError(
                        code="refused",
                        message="The model declined to answer this request.",
                    )
                    return

                text = "".join(b.text for b in final.content if b.type == "text")
                tool_uses = [b for b in final.content if b.type == "tool_use"]

                yield AssistantMessage(
                    text=text,
                    input_tokens=final.usage.input_tokens,
                    output_tokens=final.usage.output_tokens,
                )

                if final.stop_reason == "max_tokens" and tool_uses:
                    # The tool's arguments were cut off mid-JSON. They will
                    # still parse — into something plausible and wrong — so the
                    # only safe move is to refuse to run them.
                    logger.warning("llm truncated mid tool call", model=settings.anthropic_model)
                    yield StreamError(
                        code="output_truncated",
                        message="The response was cut off before the tool call was complete.",
                    )
                    return

                if not tool_uses:
                    logger.info(
                        "llm stream finished",
                        model=settings.anthropic_model,
                        stop_reason=final.stop_reason,
                        model_calls=iteration + 1,
                        input_tokens=total_input,
                        output_tokens=total_output,
                    )
                    yield StreamDone(
                        stop_reason=final.stop_reason,
                        input_tokens=total_input,
                        output_tokens=total_output,
                    )
                    return

                # RAW blocks, not our normalized ones. This is the one place the
                # SDK's own shapes are kept, and it is deliberate: `final.content`
                # still holds the thinking blocks, and the model needs its own
                # reasoning back when it continues after a tool result. Those
                # blocks never escape this function — nothing above the seam sees
                # them, and nothing persists them.
                wire_messages.append({"role": "assistant", "content": final.content})

                results: list[dict[str, Any]] = []
                for block in tool_uses:
                    # Strict tools mean this is already schema-valid, and current
                    # SDK types say so too — which is why the checker now calls this
                    # isinstance redundant. It stays as a runtime guard: the promise
                    # comes from the provider, not from anything we control, and a
                    # non-dict here would otherwise reach a tool handler.
                    tool_input = (
                        block.input
                        if isinstance(block.input, dict)  # pyright: ignore[reportUnnecessaryIsInstance]
                        else {}
                    )

                    yield ToolCall(tool_use_id=block.id, name=block.name, input=tool_input)
                    output = await execute_tool(block.name, tool_input)
                    yield ToolResult(
                        tool_use_id=block.id,
                        content=output.content,
                        is_error=output.is_error,
                        data=output.data,
                    )
                    results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": output.content,
                            "is_error": output.is_error,
                        }
                    )

                # All of a turn's results go back in ONE user message. Splitting
                # them across several is a protocol error, and even where it is
                # tolerated it teaches the model to stop asking for tools in
                # parallel.
                wire_messages.append({"role": "user", "content": results})

            # Fell out of the loop: the model kept calling tools and never
            # answered. Almost always a tool that cannot succeed — it returns an
            # error, the model retries, forever. The cap turns an infinite spend
            # into one bounded failure.
            logger.warning(
                "llm tool loop exhausted",
                model=settings.anthropic_model,
                max_iterations=settings.max_tool_iterations,
            )
            yield StreamError(
                code="tool_loop_exhausted",
                message="The model kept calling tools without reaching an answer.",
            )

        # Most specific first. A single `except APIStatusError` would collapse
        # "wait and retry" and "your key is wrong" into one outcome.
        except anthropic.RateLimitError as exc:
            logger.warning("llm rate limited", error=str(exc))
            yield StreamError(code="rate_limited", message="Rate limited. Try again shortly.")
        except anthropic.AuthenticationError:
            # Deliberately not logging the exception: its message can echo the
            # key prefix back into your logs.
            logger.error("llm auth failed")
            yield StreamError(code="auth_failed", message="Invalid or missing API key.")
        except anthropic.BadRequestError as exc:
            logger.error("llm bad request", error=str(exc))
            yield StreamError(code="bad_request", message=str(exc))
        except anthropic.APIStatusError as exc:
            logger.error("llm api error", status_code=exc.status_code, error=str(exc))
            retryable = exc.status_code >= _SERVER_ERROR_STATUS
            yield StreamError(
                code="provider_unavailable" if retryable else "bad_request",
                message="The model provider returned an error.",
            )
        except anthropic.APIConnectionError as exc:
            logger.error("llm connection failed", error=str(exc))
            yield StreamError(code="connection_failed", message="Could not reach the provider.")
        except Exception:
            logger.exception("llm unexpected error")
            yield StreamError(code="internal_error", message="Something went wrong.")

    async def complete(self, *, system: str, prompt: str) -> str | None:
        """A single cheap, short, non-streaming call.

        Deliberately not `stream`'s machinery with the knobs turned down. There
        is no tool loop, no thinking to preserve, no cancellation checkpoint and
        no event to yield — all of which exist for a turn somebody is watching.

        One broad `except` here, against the rule in CONVENTIONS.md, and the reason
        is the rule's own: a chain exists so the caller can tell "wait and
        retry" from "your key is wrong". This caller cannot act on either. Its
        entire contract is `str | None`, the failure is invisible to the user by
        construction, and every branch would end in the same `return None`. The
        status code is logged instead, which is where that distinction is
        actually worth something.
        """
        try:
            message = await self._client.messages.create(
                model=settings.anthropic_fast_model,
                max_tokens=settings.anthropic_fast_max_tokens,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            )
        except anthropic.APIError as exc:
            logger.warning(
                "llm completion failed",
                model=settings.anthropic_fast_model,
                status_code=getattr(exc, "status_code", None),
                error_type=type(exc).__name__,
            )
            return None

        # A refusal is an ordinary 200 with nothing in it, and `max_tokens` here
        # means the model ignored "at most six words" — neither is worth using.
        if message.stop_reason != "end_turn":
            logger.info(
                "llm completion unusable",
                model=settings.anthropic_fast_model,
                stop_reason=message.stop_reason,
            )
            return None

        text = "".join(b.text for b in message.content if b.type == "text").strip()
        return text or None
