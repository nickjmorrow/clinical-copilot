"""The tool registry.

Every tool the model can call is listed here once. Adding one is two lines: a
module next to find_patients.py, and an entry in `_TOOLS`.

There is exactly one tool, and that is the design rather than an early stage.
`find_patients` is the only way to reach the clinical dataset, so the set of
things this application can do to patient data is the set of things that
function does. A second tool is a second thing to audit.

This package is deliberately *below* services/ and above nothing: a tool is a
leaf. If a tool needs a database session or business logic, it should call into
services/ rather than grow its own — the handler is an adapter for the model,
not a place to put behavior.
"""

from collections.abc import Awaitable, Callable
from typing import Any

from app.llm.types import ToolDefinition, ToolOutput
from app.logging import get_logger
from app.tools import find_patients
from app.tools.base import Tool, ToolContext

logger = get_logger(__name__)

# How many times one tool may fail in a turn before the registry stops running
# it. Two, so the model gets exactly one correction — which is the retry that
# is usually right (it asked for a column it may not have, and asks again for
# one it may). A third attempt is the model guessing, and a guess against a
# clinical dataset is worse than an admission.
#
# This is not the same cap as `max_tool_iterations` in the adapter, and both
# are wanted. That one bounds the total number of model calls in a turn and
# exists so a tool that can never succeed cannot run up an unbounded bill. This
# one is semantic: it ends a specific tool's retries with an explanation the
# model can relay to the user, rather than by silently running out of loop.
MAX_TOOL_FAILURES = 2

_TOOLS: dict[str, Tool] = {tool.definition.name: tool for tool in (find_patients.FIND_PATIENTS,)}


def definitions() -> list[ToolDefinition]:
    """What the model is offered. Stable order matters: the tool list is part of
    the cached prompt prefix, and reordering it invalidates that cache."""
    return [tool.definition for tool in _TOOLS.values()]


def executor(context: ToolContext) -> Callable[[str, dict[str, Any]], Awaitable[ToolOutput]]:
    """Bind a turn's context to the registry, giving the provider a ToolExecutor.

    The adapter's contract is `(name, input) -> output` and stays that way; the
    session and the asking user ride along in the closure instead of widening
    a seam that has nothing to do with either.
    """

    async def run(name: str, tool_input: dict[str, Any]) -> ToolOutput:
        return await execute(name, tool_input, context)

    return run


async def execute(name: str, tool_input: dict[str, Any], context: ToolContext) -> ToolOutput:
    """Run one tool by name. Never raises — see app/tools/base.py.

    The two failures handled here are the ones a handler cannot handle itself: a
    name that is not in the registry (the model hallucinated a tool, or you
    removed one mid-conversation), and a handler that raised despite the rule.
    Both come back as results the model can read.
    """
    tool = _TOOLS.get(name)
    if tool is None:
        logger.warning("tool not found", tool=name)
        return ToolOutput(content=f"No tool named {name!r} exists.", is_error=True)

    if context.attempts.failures_for(name) >= MAX_TOOL_FAILURES:
        # NOT is_error. An error is an instruction to fix and retry, which is
        # the loop this is trying to end. This is a plain result saying the
        # attempts are over and the user should be told what happened.
        logger.warning("tool attempts exhausted", tool=name, failures=MAX_TOOL_FAILURES)
        return ToolOutput(
            content=(
                f"The {name!r} tool has already failed {MAX_TOOL_FAILURES} times in this "
                "turn, so it will not be run again. Do not call it a third time. Tell the "
                "user plainly what you were trying to look up and what went wrong, and ask "
                "them how they would like to proceed."
            )
        )

    logger.info("tool started", tool=name)
    try:
        output = await tool.run(tool_input, context)
    except Exception:
        # A bug in a handler, not a bad argument. Log the traceback for us; tell
        # the model only that it failed, because an exception message can carry
        # paths, queries, or worse into the conversation.
        logger.exception("tool raised", tool=name)
        return ToolOutput(content=f"The {name!r} tool failed unexpectedly.", is_error=True)

    if output.is_error:
        context.attempts.record_failure(name)

    logger.info(
        "tool finished",
        tool=name,
        is_error=output.is_error,
        failures=context.attempts.failures_for(name),
    )
    return output
