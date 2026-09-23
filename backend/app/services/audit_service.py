"""Writing, and reading back, the query audit log.

Append-only, and written on **every** attempt — answered, refused, clarified
or errored, from any surface (`via`: the model's tool, a cohort drilldown, an
explain, an export, a curator's preview). An audit log that records only
successes cannot answer the question it exists for, which is "did anyone try
to read that column".

`record_query` commits on its own rather than joining the caller's
transaction. An audit row that rolls back alongside the thing it was auditing
is not an audit row, and the case where that matters is exactly the case worth
recording: something went wrong afterwards.

The read side — `unresolved_term_report` and `summary` — is
SEMANTIC_LAYER.md § 14: the backlog for what to define next, and the same
view a PHI audit asks of this table. Read-only, and deliberately not the same
function as the write side; nothing here decides what gets logged, only what
gets shown.
"""

import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging import get_logger
from app.models import QueryAudit

logger = get_logger(__name__)

OUTCOMES = ("answered", "clarification_requested", "rejected", "error")
VIAS = ("tool", "cohort", "explain", "export", "preview", "browse")


@dataclass(frozen=True)
class QueryAttempt:
    """One question and what became of it.

    A record rather than a dozen parameters, because these fields are only
    ever meaningful together — and because the database enforces relationships
    between them (a rejection must carry a reason), which is easier to satisfy
    when they are constructed in one place.
    """

    asked_by: str
    raw_question: str
    outcome: str
    conversation_id: uuid.UUID | None = None
    resolved_terms: tuple[str, ...] = ()
    executed_sql: str | None = None
    columns_touched: tuple[str, ...] = field(default=())
    row_count: int | None = None
    rejection_reason: str | None = None
    via: str = "tool"
    # term -> version, for every definition this question resolved through.
    # What makes an old answer reproducible — the threshold it used is in
    # `clinical_definition_history`, keyed by exactly this.
    definition_versions: dict[str, int] = field(default_factory=dict)
    measures: tuple[str, ...] = ()
    group_by: tuple[str, ...] = ()


async def record_query(session: AsyncSession, attempt: QueryAttempt) -> QueryAudit:
    """Append one row. The CHECK constraints enforce the outcome/reason and via pairing."""
    if attempt.outcome not in OUTCOMES:
        message = f"unknown audit outcome {attempt.outcome!r}; expected one of {list(OUTCOMES)}"
        raise ValueError(message)
    if attempt.via not in VIAS:
        message = f"unknown audit via {attempt.via!r}; expected one of {list(VIAS)}"
        raise ValueError(message)

    entry = QueryAudit(
        conversation_id=attempt.conversation_id,
        asked_by=attempt.asked_by,
        raw_question=attempt.raw_question,
        resolved_terms=list(attempt.resolved_terms),
        executed_sql=attempt.executed_sql,
        columns_touched=sorted(set(attempt.columns_touched)),
        row_count=attempt.row_count,
        outcome=attempt.outcome,
        rejection_reason=attempt.rejection_reason,
        via=attempt.via,
        definition_versions=dict(attempt.definition_versions),
        measures=list(attempt.measures),
        group_by=list(attempt.group_by),
    )
    session.add(entry)
    await session.commit()
    await session.refresh(entry)

    # The question itself is never logged — it is a clinical question about
    # patients, and log output goes wherever logs go. It lives in the audit
    # table, which is access-controlled, and not in the log stream.
    logger.info(
        "clinical query audited",
        audit_id=str(entry.id),
        asked_by=attempt.asked_by,
        outcome=attempt.outcome,
        via=attempt.via,
        row_count=attempt.row_count,
        term_count=len(attempt.resolved_terms),
    )
    return entry


# ------------------------------------------------------------------- reading


@dataclass(frozen=True)
class UnresolvedTermEntry:
    """One phrase that did not resolve, and how often it has been asked.

    The backlog for what to define next — SEMANTIC_LAYER.md § 14. Ranked so
    the most-asked missing term is the one worth writing a definition for
    first.
    """

    raw_question: str
    count: int
    last_asked: datetime
    asked_by: tuple[str, ...]


async def unresolved_term_report(
    session: AsyncSession, *, limit: int = 50
) -> list[UnresolvedTermEntry]:
    """Every clarification the system has asked, grouped by the question that
    caused it, most frequent first.

    Grouped by `raw_question` rather than by the individual unresolved phrase:
    the audit row does not currently split out which of several terms in a
    question failed, and the raw question is what a curator would use to
    decide what a new definition should be called anyway.
    """
    result = await session.execute(
        select(QueryAudit)
        .where(QueryAudit.outcome == "clarification_requested")
        .order_by(QueryAudit.created_at.desc())
    )
    rows = result.scalars().all()

    grouped: dict[str, list[QueryAudit]] = {}
    for row in rows:
        grouped.setdefault(row.raw_question, []).append(row)

    entries = [
        UnresolvedTermEntry(
            raw_question=question,
            count=len(attempts),
            last_asked=max(a.created_at for a in attempts),
            asked_by=tuple(sorted({a.asked_by for a in attempts})),
        )
        for question, attempts in grouped.items()
    ]
    entries.sort(key=lambda entry: (entry.count, entry.last_asked), reverse=True)
    return entries[:limit]


@dataclass(frozen=True)
class AuditSummary:
    """Counts over the audit log, for the report a PHI audit asks for:
    who asked what, how often, and what happened when they did."""

    total: int
    by_outcome: dict[str, int]
    by_via: dict[str, int]
    rejected_columns: dict[str, int]
    asked_by: dict[str, int]


async def summary(session: AsyncSession, *, since: datetime | None = None) -> AuditSummary:
    """A count-only view over the whole audit log, or everything after `since`.

    Deliberately does not return the rows themselves — this is the dashboard
    number, not the drilldown. A caller wanting individual attempts reads
    `query_audit` directly, scoped by the auditor role.
    """
    statement = select(QueryAudit)
    if since is not None:
        statement = statement.where(QueryAudit.created_at >= since)
    result = await session.execute(statement)
    rows = result.scalars().all()

    rejected_columns: Counter[str] = Counter()
    for row in rows:
        if row.outcome == "rejected":
            rejected_columns.update(row.columns_touched)

    return AuditSummary(
        total=len(rows),
        by_outcome=dict(Counter(row.outcome for row in rows)),
        by_via=dict(Counter(row.via for row in rows)),
        rejected_columns=dict(rejected_columns),
        asked_by=dict(Counter(row.asked_by for row in rows)),
    )


async def count_by_outcome(session: AsyncSession) -> dict[str, int]:
    """A cheap version of `summary` for a caller that only wants the totals,
    aggregated in SQL rather than by fetching every row."""
    result = await session.execute(
        select(QueryAudit.outcome, func.count()).group_by(QueryAudit.outcome)
    )
    return dict(result.tuples().all())
