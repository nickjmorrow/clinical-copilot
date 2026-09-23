"""What a tool is.

A tool is a JSON Schema the model reads and a function the server runs. Both
halves live in one object so they cannot drift: if you widen the schema without
widening the handler, it is visible in one file.

Two rules, both enforced by convention rather than by types:

1. **Schemas are closed.** Every property declared, `required` listed,
   `additionalProperties: false`. The adapter sends tools as strict, so the
   provider guarantees the input validates before it ever reaches a handler —
   which is what lets `run` index into its input instead of defensively
   re-checking every field.

2. **Handlers do not raise.** A failure is `ToolOutput(..., is_error=True)`,
   which goes back to the model as a normal tool result. The model reads it and
   usually fixes itself. An exception would end the whole turn instead, and the
   user would see a dead stream because an argument had a typo in it.
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.types import ToolDefinition, ToolOutput


@dataclass(slots=True)
class AttemptLedger:
    """Failed tool calls so far in this turn, counted per tool.

    Mutable, and deliberately the only mutable thing a handler can reach. The
    context around it stays frozen — what a handler is allowed to know should
    not be something it can rewrite — but the count has to accumulate across
    calls within one turn, and a turn is exactly the lifetime of the ledger.

    Only failures are counted. A clarification is not a failure: asking the
    user which term they meant, getting an answer, and asking again is the loop
    working, and charging it a retry would end a conversation that was going
    fine.
    """

    failures: dict[str, int] = field(default_factory=dict)

    def record_failure(self, tool: str) -> None:
        self.failures[tool] = self.failures.get(tool, 0) + 1

    def failures_for(self, tool: str) -> int:
        return self.failures.get(tool, 0)


@dataclass(frozen=True, slots=True)
class ToolContext:
    """What a handler is allowed to know about the turn it is running inside.

    Passed explicitly rather than read from a contextvar. A tool that reaches
    into ambient state is one you cannot call from a test without building the
    ambient state first, and — more to the point here — the identity a query is
    audited against should be visible in the signature of the thing doing the
    auditing.

    The session is the turn's own. A tool does not open its own connection: a
    handler with a private session can commit work the turn later abandons.
    """

    session: AsyncSession
    user_id: str
    conversation_id: uuid.UUID | None = None
    attempts: AttemptLedger = field(default_factory=AttemptLedger)


ToolHandler = Callable[[dict[str, Any], ToolContext], Awaitable[ToolOutput]]


@dataclass(frozen=True, slots=True)
class Tool:
    definition: ToolDefinition
    run: ToolHandler
