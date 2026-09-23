"""Answering one clinical question, end to end.

**The only path from a question to rows.** Every route into this module —
the model's tool, a cohort drilldown, an export, a curator's preview, the
patient browser — ends up here, and here alone writes an audit row before returning.
That is deliberate: "answered without being logged" is not a reachable state
rather than a rule someone has to remember. `via` on every call says which
surface asked, so "did the model ask for it" and "did anyone export it" stay
answerable as different questions.

The order of the guardrails matters and is the order they appear in:

1. resolve the terms — an incomplete resolution becomes a clarification, never
   a narrower query
2. resolve the columns (cohort) or the measures/dimensions (aggregate) — an
   unknown or restricted column, or an unresolved measure, is a refusal
3. assemble — parameterised SQL from validated predicates, and nothing else in
   this codebase writes any
4. execute under a hard row cap
5. audit, on every one of those outcomes including the failures

Nothing is executed before every check has passed, which is what "fail closed"
means here: there is no partially-guarded query, only a query or a refusal.

**Two query shapes, one entry point.** `answer_question` runs a cohort listing
when `measures` is empty and an aggregate when it is not — the model decides
which question it is asking by whether it names a measure, the same way it
decides everything else here: by picking defined terms.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any, cast

from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.clinical.assembler import (
    aggregate_query,
    browse_patients_count,
    browse_patients_query,
    medication_aggregate_query,
    patient_query,
    touched_columns,
    unmeasured_query,
)
from app.clinical.columns import MAX_ROWS, ColumnAccessError, resolve_columns
from app.clinical.predicates import (
    InvalidPredicateError,
    ObservationThreshold,
    Predicate,
)
from app.logging import get_logger
from app.services import audit_service, authz_service, catalog_service, definition_service
from app.services.audit_service import QueryAttempt
from app.services.definition_service import ResolvedTerm

logger = get_logger(__name__)


@dataclass(frozen=True)
class Asker:
    """Who is asking, and in which conversation.

    One value rather than two parameters threaded through every branch: these
    are always needed together, every audit row carries both, and a signature
    that cannot accidentally record a question against the wrong user is worth
    more than the line it saves.
    """

    user_id: str
    conversation_id: uuid.UUID | None = None
    # Row-level scope, from `authz_service.get_scope_states`. `None` is
    # unconfined; threaded through so every query this module assembles
    # carries the same restriction a hand-typed one would.
    scope_states: tuple[str, ...] | None = None
    # From `authz_service.get_roles`. Decides which identifying columns
    # `resolve_columns` permits — SEMANTIC_LAYER.md § 19's per-role column
    # policy. Empty, not `None`: there is no "unset" reading for roles the
    # way there is for scope, so a caller that forgot to fetch them gets the
    # same denial as a caller with genuinely no roles, never the unconfined
    # one `scope_states=None` would give for scope.
    roles: frozenset[str] = frozenset()


async def build_asker(
    session: AsyncSession, *, user_id: str, conversation_id: uuid.UUID | None = None
) -> Asker:
    """The one way an `Asker` gets built: fetch scope, fetch roles, wrap them.

    Every caller — the chat tool, the cohort routes, a saved-question run, a
    definition preview — goes through this, because an `Asker` built by hand
    from a user id alone is unconfined: it silently drops the caller's scope.
    """
    scope_states = await authz_service.get_scope_states(session, user_id=user_id)
    roles = await authz_service.get_roles(session, user_id=user_id)
    return Asker(
        user_id=user_id,
        conversation_id=conversation_id,
        scope_states=tuple(scope_states) if scope_states is not None else None,
        roles=roles,
    )


@dataclass(frozen=True)
class UnmeasuredCount:
    """How many patients an observation threshold silently dropped: they
    matched everything else asked and were never measured for this.

    SEMANTIC_LAYER.md § 10 — failing to measure should not fail open any more
    than failing to resolve does. Computed only when the question resolved to
    exactly one observation threshold; see `_unmeasured_counts`.
    """

    term: str
    count: int


@dataclass(frozen=True)
class ClinicalAnswer:
    """What the tool hands back to the model.

    `resolved` carries each term's description and the reasoning behind its
    threshold, because the answer displays them. A clinician verifying "why
    these patients" needs the definition, not just the count — that is the
    trust requirement the definitions layer exists to meet.

    `aggregate` distinguishes the two query shapes: a cohort listing has rows
    of patients, an aggregate has rows of measures grouped by dimensions. Both
    ride in `rows`/`columns` so a caller that only wants "did this work" does
    not need a second code path.
    """

    outcome: str
    aggregate: bool = False
    columns: tuple[str, ...] = ()
    rows: tuple[dict[str, Any], ...] = ()
    row_count: int = 0
    truncated: bool = False
    resolved: tuple[ResolvedTerm, ...] = ()
    resolved_measures: tuple[definition_service.ResolvedMeasure, ...] = ()
    resolved_dimensions: tuple[definition_service.ResolvedDimension, ...] = ()
    unmeasured: tuple[UnmeasuredCount, ...] = ()
    executed_sql: str | None = None
    # Which dataset this ran against — SEMANTIC_LAYER.md § 1's "answer" level
    # of provenance: not just the SQL, but what it ran against and when that
    # was loaded. `None` only before the first seed, or for an outcome that
    # never reached execution (a clarification, a rejection).
    dataset: catalog_service.DatasetProvenance | None = None
    reason: str | None = None
    unresolved: tuple[str, ...] = ()
    vocabulary: tuple[dict[str, Any], ...] = field(default=())

    @property
    def ok(self) -> bool:
        return self.outcome == "answered"


async def answer_question(  # noqa: PLR0913 — the guardrail order in the module docstring is the argument list
    session: AsyncSession,
    asker: Asker,
    *,
    question: str,
    terms: Sequence[str],
    columns: Sequence[str] | None = None,
    measures: Sequence[str] = (),
    group_by: Sequence[str] = (),
    today: date | None = None,
    via: str = "tool",
) -> ClinicalAnswer:
    """Resolve, guard, assemble, execute, audit. Never raises for a bad question."""
    as_of = today or date.today()  # noqa: DTZ011 — a calendar date, not a timestamp

    resolution = await definition_service.resolve_terms(session, terms=terms)
    if not resolution.is_complete:
        return await _clarify(session, asker, question=question, resolution=resolution, via=via)

    if measures:
        return await _answer_aggregate(
            session,
            asker,
            question=question,
            resolution=resolution,
            measures=measures,
            group_by=group_by,
            today=as_of,
            via=via,
        )
    return await _answer_cohort(
        session,
        asker,
        question=question,
        resolution=resolution,
        columns=columns,
        today=as_of,
        via=via,
    )


async def _answer_cohort(  # noqa: PLR0913 — the guardrail order in the module docstring is the argument list
    session: AsyncSession,
    asker: Asker,
    *,
    question: str,
    resolution: definition_service.Resolution,
    columns: Sequence[str] | None,
    today: date,
    via: str,
) -> ClinicalAnswer:
    predicates = [resolved.predicate for resolved in resolution.resolved]
    term_names = tuple(resolved.term for resolved in resolution.resolved)
    versions = {resolved.term: resolved.version for resolved in resolution.resolved}

    try:
        selected, column_names = resolve_columns(columns, today=today, roles=asker.roles)
    except ColumnAccessError as denied:
        return await _reject(
            session,
            asker,
            question=question,
            terms=term_names,
            reason=denied.reason,
            columns_touched=denied.denied,
            via=via,
        )

    try:
        # One more than the cap, so "there are more" is knowable without a
        # second COUNT over the same predicates.
        query = patient_query(
            predicates, today=today, columns=selected, scope_states=asker.scope_states
        ).limit(MAX_ROWS + 1)
    except InvalidPredicateError as invalid:
        return await _reject(
            session, asker, question=question, terms=term_names, reason=str(invalid), via=via
        )

    statement = _render(query)
    touched = tuple(
        sorted({*touched_columns(predicates), *(f"patients.{c}" for c in column_names)})
    )

    try:
        result = await session.execute(query)
        fetched = result.mappings().all()
    except SQLAlchemyError as error:
        return await _error(
            session,
            asker,
            question=question,
            terms=term_names,
            statement=statement,
            touched=touched,
            error=error,
            via=via,
            resolved=resolution.resolved,
        )

    truncated = len(fetched) > MAX_ROWS
    rows = tuple(dict(row) for row in fetched[:MAX_ROWS])
    unmeasured = await _unmeasured_counts(session, asker, resolution.resolved, today=today)

    await audit_service.record_query(
        session,
        QueryAttempt(
            asked_by=asker.user_id,
            raw_question=question,
            outcome="answered",
            conversation_id=asker.conversation_id,
            resolved_terms=term_names,
            executed_sql=statement,
            columns_touched=touched,
            row_count=len(rows),
            via=via,
            definition_versions=versions,
        ),
    )

    return ClinicalAnswer(
        outcome="answered",
        columns=column_names,
        rows=rows,
        row_count=len(rows),
        truncated=truncated,
        resolved=resolution.resolved,
        unmeasured=unmeasured,
        executed_sql=statement,
        dataset=await catalog_service.current_dataset(session),
    )


async def _answer_aggregate(  # noqa: PLR0913 — the guardrail order in the module docstring is the argument list
    session: AsyncSession,
    asker: Asker,
    *,
    question: str,
    resolution: definition_service.Resolution,
    measures: Sequence[str],
    group_by: Sequence[str],
    today: date,
    via: str,
) -> ClinicalAnswer:
    predicates = [resolved.predicate for resolved in resolution.resolved]
    term_names = tuple(resolved.term for resolved in resolution.resolved)
    versions = {resolved.term: resolved.version for resolved in resolution.resolved}

    measure_resolution = await definition_service.resolve_measures(session, names=measures)
    dimension_resolution = await definition_service.resolve_dimensions(session, names=group_by)
    if not measure_resolution.is_complete or not dimension_resolution.is_complete:
        reason = _unresolved_measure_reason(measure_resolution, dimension_resolution)
        return await _reject(
            session,
            asker,
            question=question,
            terms=term_names,
            reason=reason,
            via=via,
        )
    versions.update({m.term: m.version for m in measure_resolution.resolved})
    versions.update({d.term: d.version for d in dimension_resolution.resolved})

    dimension_entities = {d.entity for d in dimension_resolution.resolved}
    if len(dimension_entities) > 1:
        reason = (
            "can't group by more than one entity at once — "
            f"{', '.join(sorted(dimension_entities))} would need separate questions"
        )
        return await _reject(
            session, asker, question=question, terms=term_names, reason=reason, via=via
        )
    build_query = (
        medication_aggregate_query if dimension_entities == {"medication"} else aggregate_query
    )

    try:
        query = build_query(
            predicates,
            measures=[(m.term, m.measure) for m in measure_resolution.resolved],
            dimensions=[(d.term, d.dimension) for d in dimension_resolution.resolved],
            today=today,
            scope_states=asker.scope_states,
        ).limit(MAX_ROWS + 1)
    except InvalidPredicateError as invalid:
        return await _reject(
            session, asker, question=question, terms=term_names, reason=str(invalid), via=via
        )

    statement = _render(query)
    touched = tuple(
        sorted(
            touched_columns(
                predicates,
                measures=[m.measure for m in measure_resolution.resolved],
                dimensions=[d.dimension for d in dimension_resolution.resolved],
            )
        )
    )

    try:
        result = await session.execute(query)
        fetched = result.mappings().all()
    except SQLAlchemyError as error:
        return await _error(
            session,
            asker,
            question=question,
            terms=term_names,
            statement=statement,
            touched=touched,
            error=error,
            via=via,
            resolved=resolution.resolved,
        )

    truncated = len(fetched) > MAX_ROWS
    rows = tuple(dict(row) for row in fetched[:MAX_ROWS])
    columns = (
        tuple(rows[0].keys())
        if rows
        else (
            *(d.term for d in dimension_resolution.resolved),
            *(m.term for m in measure_resolution.resolved),
        )
    )

    await audit_service.record_query(
        session,
        QueryAttempt(
            asked_by=asker.user_id,
            raw_question=question,
            outcome="answered",
            conversation_id=asker.conversation_id,
            resolved_terms=term_names,
            executed_sql=statement,
            columns_touched=touched,
            row_count=len(rows),
            via=via,
            definition_versions=versions,
            measures=tuple(m.term for m in measure_resolution.resolved),
            group_by=tuple(d.term for d in dimension_resolution.resolved),
        ),
    )

    return ClinicalAnswer(
        outcome="answered",
        aggregate=True,
        columns=columns,
        rows=rows,
        row_count=len(rows),
        truncated=truncated,
        resolved=resolution.resolved,
        resolved_measures=measure_resolution.resolved,
        resolved_dimensions=dimension_resolution.resolved,
        executed_sql=statement,
        dataset=await catalog_service.current_dataset(session),
    )


async def preview_logic(
    session: AsyncSession, asker: Asker, *, kind: str, logic: object
) -> int | None:
    """Check a *proposed* definition's `logic`, and count what a filter matches.

    Every kind is parsed, so a curator gets the same shape feedback before
    saving that a create or an update would give after — SEMANTIC_LAYER.md
    § 6's "an editor can tell you before you save". Only a filter has a cohort
    to count; a measure or a dimension that parses returns `None`.

    A filter can be composed from terms that already exist, and the assembler
    only ever sees predicates with those references substituted — so the
    proposal gets the same substitution `load_vocabulary` gives a saved one.
    Raises `InvalidPredicateError` for anything that does not parse or
    resolve.
    """
    built = definition_service.validate_shape(kind, logic)
    if kind != "filter":
        return None
    predicate = await definition_service.resolve_references(session, cast("Predicate", built))
    return await preview_definition(session, asker, predicate=predicate)


async def preview_definition(
    session: AsyncSession, asker: Asker, *, predicate: Predicate, today: date | None = None
) -> int:
    """How many patients a *proposed* predicate would match, without saving it.

    The impact preview an editor needs before committing a threshold change —
    SEMANTIC_LAYER.md § 6. Deliberately returns a bare count rather than rows:
    a curator previewing an edit does not need patient identifiers, and a
    count-only path is cheap enough to run on every keystroke's worth of edit.
    Still audited, `via="preview"` — a dry run against patient data is still a
    query against patient data.
    """
    as_of = today or date.today()  # noqa: DTZ011 — a calendar date, not a timestamp
    query = patient_query([predicate], today=as_of, scope_states=asker.scope_states)
    statement = _render(query)
    try:
        count = await session.scalar(select(func.count()).select_from(query.subquery())) or 0
    except SQLAlchemyError as error:
        await audit_service.record_query(
            session,
            QueryAttempt(
                asked_by=asker.user_id,
                raw_question="(definition preview)",
                outcome="error",
                conversation_id=asker.conversation_id,
                executed_sql=statement,
                rejection_reason=type(error).__name__,
                via="preview",
            ),
        )
        raise

    await audit_service.record_query(
        session,
        QueryAttempt(
            asked_by=asker.user_id,
            raw_question="(definition preview)",
            outcome="answered",
            conversation_id=asker.conversation_id,
            executed_sql=statement,
            row_count=count,
            via="preview",
        ),
    )
    return count


@dataclass(frozen=True)
class BrowseResult:
    """One page of the raw patient table, for a curator or auditor —
    SEMANTIC_LAYER.md § 3's governed table browser.

    Not a `ClinicalAnswer`: there is no question here, no resolved terms —
    just rows, the columns they carry, where this page sits in the whole
    scoped population, and which dataset they came from. Keeping it a
    separate, smaller shape is what stops `ClinicalAnswer` growing pagination
    fields every other caller would carry around unused.
    """

    outcome: str
    columns: tuple[str, ...] = ()
    rows: tuple[dict[str, Any], ...] = ()
    total: int = 0
    offset: int = 0
    limit: int = 0
    dataset: catalog_service.DatasetProvenance | None = None
    reason: str | None = None

    @property
    def ok(self) -> bool:
        return self.outcome == "answered"


async def browse_patients(
    session: AsyncSession,
    asker: Asker,
    *,
    columns: Sequence[str] | None,
    offset: int,
    limit: int,
    today: date | None = None,
) -> BrowseResult:
    """A page of every patient in scope, no filter required.

    The one place this module deliberately skips `resolve_terms` — there is
    no question to resolve a term against, only "show me the data". Still
    goes through the same column allowlist and per-role policy, the same
    row-level scope, and its own audited `via="browse"`, because looking at
    the raw rows is still looking at patient data.
    """
    as_of = today or date.today()  # noqa: DTZ011 — a calendar date, not a timestamp
    capped_limit = min(limit, MAX_ROWS)

    try:
        selected, column_names = resolve_columns(columns, today=as_of, roles=asker.roles)
    except ColumnAccessError as denied:
        await audit_service.record_query(
            session,
            QueryAttempt(
                asked_by=asker.user_id,
                raw_question="(browse)",
                outcome="rejected",
                conversation_id=asker.conversation_id,
                columns_touched=denied.denied,
                rejection_reason=denied.reason,
                via="browse",
            ),
        )
        return BrowseResult(outcome="rejected", reason=denied.reason)

    query = browse_patients_query(
        columns=selected, scope_states=asker.scope_states, offset=offset, limit=capped_limit
    )
    statement = _render(query)
    touched = tuple(sorted(f"patients.{c}" for c in column_names))

    try:
        result = await session.execute(query)
        rows = tuple(dict(row) for row in result.mappings())
        total = await session.scalar(browse_patients_count(scope_states=asker.scope_states)) or 0
    except SQLAlchemyError as error:
        logger.error("patient browse failed", asked_by=asker.user_id, exc_info=error)
        await audit_service.record_query(
            session,
            QueryAttempt(
                asked_by=asker.user_id,
                raw_question="(browse)",
                outcome="error",
                conversation_id=asker.conversation_id,
                executed_sql=statement,
                columns_touched=touched,
                rejection_reason=type(error).__name__,
                via="browse",
            ),
        )
        return BrowseResult(outcome="error", reason="the query could not be executed")

    await audit_service.record_query(
        session,
        QueryAttempt(
            asked_by=asker.user_id,
            raw_question="(browse)",
            outcome="answered",
            conversation_id=asker.conversation_id,
            executed_sql=statement,
            columns_touched=touched,
            row_count=len(rows),
            via="browse",
        ),
    )

    return BrowseResult(
        outcome="answered",
        columns=column_names,
        rows=rows,
        total=total,
        offset=offset,
        limit=capped_limit,
        dataset=await catalog_service.current_dataset(session),
    )


async def _unmeasured_counts(
    session: AsyncSession, asker: Asker, resolved: Sequence[ResolvedTerm], *, today: date
) -> tuple[UnmeasuredCount, ...]:
    """For each observation threshold among the resolved terms, on its own —
    not composed inside `any_of`/`all_of`/`not` — how many patients matched
    every *other* predicate but have no numeric value for this one.

    Restricted to top-level, uncomposed thresholds: attributing "unmeasured"
    through a boolean combinator (was it this leg, or the other one, that had
    no data?) is a harder question than this pass answers, so it reports the
    cases where the attribution is unambiguous and says nothing about the
    rest, rather than guessing.
    """
    counts: list[UnmeasuredCount] = []
    for index, term in enumerate(resolved):
        if not isinstance(term.predicate, ObservationThreshold):
            continue
        others = [other.predicate for i, other in enumerate(resolved) if i != index]
        query = unmeasured_query(
            term.predicate, other=others, today=today, scope_states=asker.scope_states
        )
        count = await session.scalar(query) or 0
        counts.append(UnmeasuredCount(term=term.term, count=count))
    return tuple(counts)


async def _clarify(
    session: AsyncSession,
    asker: Asker,
    *,
    question: str,
    resolution: definition_service.Resolution,
    via: str,
) -> ClinicalAnswer:
    """A term did not resolve, so ask rather than answer a narrower question.

    The vocabulary goes back with it. "I don't know that term" is not an
    actionable reply; "I don't know that term, here are the ones I do know" is
    one the model can turn into a single useful question.
    """
    reason = _unresolved_reason(resolution)
    await audit_service.record_query(
        session,
        QueryAttempt(
            asked_by=asker.user_id,
            raw_question=question,
            outcome="clarification_requested",
            conversation_id=asker.conversation_id,
            resolved_terms=tuple(r.term for r in resolution.resolved),
            via=via,
        ),
    )
    return ClinicalAnswer(
        outcome="clarification_requested",
        resolved=resolution.resolved,
        unresolved=resolution.unresolved,
        reason=reason,
        vocabulary=tuple(await definition_service.vocabulary(session)),
    )


async def _reject(  # noqa: PLR0913 — every field is what an audit row needs; see the module docstring
    session: AsyncSession,
    asker: Asker,
    *,
    question: str,
    terms: Sequence[str],
    reason: str,
    via: str,
    columns_touched: Sequence[str] = (),
) -> ClinicalAnswer:
    await audit_service.record_query(
        session,
        QueryAttempt(
            asked_by=asker.user_id,
            raw_question=question,
            outcome="rejected",
            conversation_id=asker.conversation_id,
            resolved_terms=tuple(terms),
            columns_touched=tuple(columns_touched),
            rejection_reason=reason,
            via=via,
        ),
    )
    return ClinicalAnswer(outcome="rejected", reason=reason)


async def _error(  # noqa: PLR0913 — every field is what an audit row needs; see the module docstring
    session: AsyncSession,
    asker: Asker,
    *,
    question: str,
    terms: Sequence[str],
    statement: str,
    touched: Sequence[str],
    error: SQLAlchemyError,
    via: str,
    resolved: Sequence[ResolvedTerm],
) -> ClinicalAnswer:
    # The message may carry SQL and column names, so it goes to the audit row
    # and the server log — never to the model, which would put it in the
    # conversation. See CONVENTIONS.md > Tools. `exc_info=error` rather than
    # `.exception()`: this runs inside the caller's `except` block but is not
    # textually inside one itself, which is what `.exception()` requires.
    logger.error("clinical query failed", asked_by=asker.user_id, exc_info=error)
    await audit_service.record_query(
        session,
        QueryAttempt(
            asked_by=asker.user_id,
            raw_question=question,
            outcome="error",
            conversation_id=asker.conversation_id,
            resolved_terms=tuple(terms),
            executed_sql=statement,
            columns_touched=tuple(touched),
            rejection_reason=type(error).__name__,
            via=via,
        ),
    )
    return ClinicalAnswer(
        outcome="error", resolved=tuple(resolved), reason="the query could not be executed"
    )


def _unresolved_reason(resolution: definition_service.Resolution) -> str:
    parts: list[str] = []
    if resolution.unresolved:
        parts.append(f"no definition for: {list(resolution.unresolved)}")
    for term, why in resolution.invalid:
        parts.append(f"the definition of {term!r} is unusable ({why})")
    return "; ".join(parts)


def _unresolved_measure_reason(
    measures: definition_service.MeasureResolution,
    dimensions: definition_service.DimensionResolution,
) -> str:
    parts: list[str] = []
    if measures.unresolved:
        parts.append(f"no measure defined for: {list(measures.unresolved)}")
    for term, why in measures.invalid:
        parts.append(f"the measure {term!r} is unusable ({why})")
    if dimensions.unresolved:
        parts.append(f"no dimension defined for: {list(dimensions.unresolved)}")
    for term, why in dimensions.invalid:
        parts.append(f"the dimension {term!r} is unusable ({why})")
    return "; ".join(parts)


def _render(query: Any) -> str:
    """The SQL as executed, for the audit row.

    Literal-bound on purpose — this one is a record of what ran, and an audit
    entry reading `value < %(value_1)s` answers nothing six months later. It is
    never executed, only stored.
    """
    compiled = query.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    return str(compiled)
