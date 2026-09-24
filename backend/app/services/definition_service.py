"""Reading and writing the clinical definitions layer.

**What is cached here, and what deliberately is not.**

The definitions are cached. Patient answers are not, and that asymmetry is the
whole of the caching design.

Caching an answer to a clinical question means serving yesterday's renal
function to today's question. A patient whose eGFR has just fallen is exactly
the patient the query exists to surface, and a cache is a mechanism for not
surfacing them. No TTL makes that safe — it only sets how long the system is
allowed to be confidently wrong — so there is no answer cache and there should
not be one.

The definitions layer has the opposite profile. It is a handful of rows that
change when a person edits them, it is read at least twice per turn (once to
build the prompt, once to resolve the terms), and every read re-parses and
re-validates the same JSONB. Caching it removes those queries and the repeated
validation, and the worst case is that a threshold someone just edited takes
`CACHE_TTL_SECONDS` to take effect. `invalidate()` exists so the one thing that
rewrites the table in this codebase — the CRUD below — does not even have to
wait.

The bridge between a term the model picked and a predicate the assembler can
build. Everything that decides *what* a term means lives in the database row;
everything that decides whether the row is usable lives in
`app/clinical/predicates.py`. This module fetches, resolves references, checks
codes against the loaded dataset, and writes changes down with history.

**Three kinds, one table.** A `filter` selects patients, a `measure`
aggregates over them, a `dimension` groups them — see `ClinicalDefinition` in
`app/models.py`. Only a filter may reference another term (`{"type": "term",
...}` inside its `logic`); measures and dimensions are always leaves.
References are substituted here, against the *whole* vocabulary regardless of
status — a published filter composing a draft one is how a new term gets
reviewed before it is offered on its own — and a cycle is refused at load
rather than recursing forever.

**Only `status = 'published'` reaches the model.** `vocabulary()`,
`resolve_terms()`, `resolve_measures()` and `resolve_dimensions()` all filter
to it. `list_definitions(include_unpublished=True)` and `load_vocabulary()`
itself do not, because an editor reviewing a draft, and a filter composed from
one, both need to see it.

Matching happens in Python rather than in SQL. There are a handful of
definitions and they are read on every question, so the whole table is one
query and a dictionary — a JSONB containment query against `synonyms` would be
more SQL for less clarity at this size. If the vocabulary ever reaches the
hundreds, this is the thing to move back into the database.
"""

import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Final, cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clinical.assembler import patient_query
from app.clinical.predicates import (
    Dimension,
    InvalidPredicateError,
    Invariant,
    Measure,
    ObservationAggregate,
    Predicate,
    observation_codes,
    parse_dimension,
    parse_invariants,
    parse_measure,
    parse_predicate,
    substitute,
)
from app.logging import get_logger
from app.models import (
    ClinicalDefinition,
    ClinicalDefinitionHistory,
    DatasetMeta,
    ObservationCatalog,
)

logger = get_logger(__name__)

# Long enough that a burst of questions costs one query, short enough that an
# edited threshold takes effect while someone is still looking at the screen.
CACHE_TTL_SECONDS = 30.0

ENTITIES: Final = ("patient", "medication", "observation")
KINDS: Final = ("filter", "measure", "dimension")
STATUSES: Final = ("draft", "published", "deprecated")


class DefinitionConflictError(ValueError):
    """A term or synonym is already claimed by another definition."""


BuiltLogic = Predicate | Measure | Dimension


@dataclass(frozen=True)
class Definition:
    """One definition, parsed and validated, detached from any session.

    Plain values rather than an ORM row on purpose: a cached `ClinicalDefinition`
    is an instance bound to the session that loaded it, and reading it from the
    next request is either a detached-instance error or a silent lazy load.

    Holds `id` and `version` — absent from the previous shape of this class —
    because the CRUD and the audit both need to say *which* row and *which cut
    of it* an answer or an edit refers to.
    """

    id: uuid.UUID
    term: str
    kind: str
    entity: str
    status: str
    description: str
    notes: str
    synonyms: tuple[str, ...]
    invariants: tuple[Invariant, ...]
    version: int
    built: BuiltLogic | None
    invalid_reason: str | None


@dataclass(frozen=True)
class Vocabulary:
    """Every definition, indexed for lookup. Immutable, so it is safe to share.

    `definitions` is every row, any status — what an editor or `check_model`
    needs. `published_by_key` is the model-facing index: canonical term and
    synonym, normalised, published only.
    """

    definitions: tuple[Definition, ...]
    published_by_key: dict[str, Definition]


_cache: tuple[float, Vocabulary] | None = None


def invalidate() -> None:
    """Drop the cached vocabulary. Called by anything that writes the table."""
    global _cache  # noqa: PLW0603 — module-level cache; the alternative is a singleton class
    _cache = None


async def load_vocabulary(session: AsyncSession, *, use_cache: bool = True) -> Vocabulary:
    """The definitions, parsed, substituted and reused until the TTL expires."""
    global _cache  # noqa: PLW0603 — see invalidate()

    if use_cache and _cache is not None:
        cached_at, vocabulary = _cache
        if time.monotonic() - cached_at < CACHE_TTL_SECONDS:
            return vocabulary

    rows = await list_definitions(session, include_unpublished=True)
    present = await _catalog_codes(session)
    by_term: dict[str, ClinicalDefinition] = {row.term: row for row in rows}

    # Resolved on demand and memoised here, so a term referenced by several
    # others is only substituted once, and a definition processed before the
    # term it depends on still resolves correctly regardless of row order.
    resolved: dict[str, Predicate | None] = {}
    reasons: dict[str, str] = {}

    def resolve(term: str, chain: tuple[str, ...]) -> Predicate:
        if term in chain:
            cycle = " -> ".join((*chain, term))
            message = f"cyclical term reference: {cycle}"
            raise InvalidPredicateError(message)
        if term in resolved:
            cached = resolved[term]
            if cached is None:
                raise InvalidPredicateError(reasons.get(term, f"{term!r} is unusable"))
            return cached
        row = by_term.get(term)
        if row is None:
            message = f"no definition named {term!r}"
            raise InvalidPredicateError(message)
        if row.kind != "filter":
            message = f"{term!r} is a {row.kind}, not a filter, and cannot be referenced by one"
            raise InvalidPredicateError(message)
        predicate = substitute(parse_predicate(row.logic), lambda t: resolve(t, (*chain, term)))
        resolved[term] = predicate
        return predicate

    definitions: list[Definition] = []
    for row in rows:
        invalid_reason: str | None = None
        built: BuiltLogic | None = None
        try:
            if row.kind == "filter":
                built = resolve(row.term, ())
                _check_codes(row.term, observation_codes(built), present)
            elif row.kind == "measure":
                measure = parse_measure(row.logic)
                if isinstance(measure, ObservationAggregate):
                    _check_codes(row.term, ((measure.codes, measure.units),), present)
                built = measure
            else:
                built = parse_dimension(row.logic)
        except InvalidPredicateError as error:
            invalid_reason = str(error)
            resolved.setdefault(row.term, None)
            reasons[row.term] = invalid_reason
            logger.error(
                "clinical definition is unusable",
                definition_id=str(row.id),
                term=row.term,
                kind=row.kind,
                reason=invalid_reason,
            )
        try:
            # Invariants are metadata about a filter, not its filtering logic —
            # a malformed one (which write-time validation should already have
            # refused) does not disable the predicate itself, only its own
            # check_model() coverage.
            invariants = parse_invariants(row.invariants) if row.kind == "filter" else ()
        except InvalidPredicateError:
            invariants = ()

        definitions.append(
            Definition(
                id=row.id,
                term=row.term,
                kind=row.kind,
                entity=row.entity,
                status=row.status,
                description=row.description,
                notes=row.notes,
                synonyms=tuple(str(s) for s in row.synonyms),
                invariants=invariants,
                version=row.version,
                built=built,
                invalid_reason=invalid_reason,
            )
        )

    published_by_key: dict[str, Definition] = {}
    for definition in definitions:
        if definition.status == "published":
            published_by_key.setdefault(_normalise(definition.term), definition)
    for definition in definitions:
        if definition.status == "published":
            for synonym in definition.synonyms:
                # A canonical term always wins over another definition's synonym.
                published_by_key.setdefault(_normalise(synonym), definition)

    vocabulary = Vocabulary(definitions=tuple(definitions), published_by_key=published_by_key)
    _cache = (time.monotonic(), vocabulary)
    logger.info("clinical vocabulary loaded", definitions=len(definitions))
    return vocabulary


# ------------------------------------------------------------- read, listing


async def list_definitions(
    session: AsyncSession, *, include_unpublished: bool = False
) -> list[ClinicalDefinition]:
    """Every definition, ordered by term so the prompt is stable between calls.

    Published only unless `include_unpublished` — the curator surfaces and
    `load_vocabulary`'s own reference graph want everything; the model and the
    read-only context panel want only what has been signed off.
    """
    statement = select(ClinicalDefinition).order_by(ClinicalDefinition.term)
    if not include_unpublished:
        statement = statement.where(ClinicalDefinition.status == "published")
    result = await session.execute(statement)
    return list(result.scalars().all())


async def get_definition(
    session: AsyncSession, *, definition_id: uuid.UUID
) -> ClinicalDefinition | None:
    """One definition by id, any status. `None` for a curator surface to turn
    into a 404 — every write route needs this fetch before it can call
    `update_definition`/`delete_definition`, which both take the ORM row."""
    return await session.get(ClinicalDefinition, definition_id)


async def resolve_references(session: AsyncSession, predicate: Predicate) -> Predicate:
    """Substitute every `TermReference` inside a predicate that has not been
    saved anywhere — the impact preview's use case. A composed proposal
    ("all_of" over two `term` references, the running example's own shape)
    otherwise reaches `app/clinical/assembler.py` with an unresolved
    reference still in it, which it correctly refuses: the assembler's
    contract is that only `load_vocabulary` hands it predicates, and only
    after substitution. This is the same substitution, run once against the
    current vocabulary for a predicate that is not itself in it yet.

    Raises `InvalidPredicateError` for a reference to a term that does not
    exist, is not a filter, or did not itself build — the same failure shape
    `create_definition`/`update_definition` raise for a shape problem, so the
    route needs only one `except` for both.
    """
    vocab = await load_vocabulary(session)
    by_term = {d.term: d for d in vocab.definitions if d.kind == "filter"}

    def lookup(term: str) -> Predicate:
        found = by_term.get(term)
        if found is None:
            message = f"no filter named {term!r}"
            raise InvalidPredicateError(message)
        if found.built is None:
            message = f"the definition of {term!r} is unusable ({found.invalid_reason})"
            raise InvalidPredicateError(message)
        return cast("Predicate", found.built)

    return substitute(predicate, lookup)


async def definition_history(
    session: AsyncSession, *, definition_id: uuid.UUID
) -> list[ClinicalDefinitionHistory]:
    """Every version a definition has had, oldest first. Not a foreign-key join —
    see `ClinicalDefinitionHistory`'s docstring for why."""
    result = await session.execute(
        select(ClinicalDefinitionHistory)
        .where(ClinicalDefinitionHistory.definition_id == definition_id)
        .order_by(ClinicalDefinitionHistory.version, ClinicalDefinitionHistory.created_at)
    )
    return list(result.scalars().all())


async def vocabulary(session: AsyncSession) -> list[dict[str, Any]]:
    """The definitions layer as the model sees it: terms, kinds, meanings.

    Deliberately excludes `logic`. The model chooses *which* term applies; it
    has no use for the threshold, and showing it invites the model to reason
    about the number instead of the name — which is the failure this whole
    architecture exists to prevent.
    """
    vocab = await load_vocabulary(session)
    return [
        {
            "term": definition.term,
            "kind": definition.kind,
            "means": definition.description,
            "also_called": list(definition.synonyms),
        }
        for definition in vocab.definitions
        if definition.status == "published"
    ]


async def with_vocabulary(session: AsyncSession, *, base: str) -> str:
    """The system prompt, with the hospital's defined terms appended.

    Composed per turn rather than written into `Settings.system_prompt`,
    because the vocabulary is data: it lives in a table someone edits, and a
    prompt that names the terms while the table defines them is two sources of
    truth waiting to disagree.

    Grouped by kind so the model can tell a filter it may pass in `terms` apart
    from a measure it may pass in `measures` and a dimension in `group_by` —
    three arrays on the tool, and this is where it learns which name goes in
    which one.
    """
    entries = await vocabulary(session)
    if not entries:
        return base

    lines = ["", "", "The clinical terms this hospital defines, and what they mean:", ""]
    for label, kind in (("Filters", "filter"), ("Measures", "measure"), ("Group by", "dimension")):
        matching = [entry for entry in entries if entry["kind"] == kind]
        if not matching:
            continue
        lines.append(f"{label}:")
        for entry in matching:
            lines.append(f"- {entry['term']}: {entry['means']}")
            if synonyms := entry["also_called"]:
                lines.append(f"  (also accepted: {', '.join(str(s) for s in synonyms)})")
        lines.append("")
    lines.append(
        "These are the only terms `find_patients` understands. If a question needs a "
        "concept that is not on this list, say so and ask the user rather than "
        "substituting one of your own."
    )
    return base + "\n".join(lines)


# --------------------------------------------------------------- resolution


@dataclass(frozen=True)
class ResolvedTerm:
    """A filter term the model asked for, and what it turned out to mean.

    Carries `description` and `notes` because the answer shows them, and
    `version` because the audit row cites exactly this cut of the definition —
    what makes an old answer reproducible.
    """

    term: str
    matched_on: str
    predicate: Predicate
    description: str
    notes: str
    version: int


@dataclass(frozen=True)
class ResolvedMeasure:
    term: str
    matched_on: str
    measure: Measure
    description: str
    notes: str
    version: int


@dataclass(frozen=True)
class ResolvedDimension:
    term: str
    matched_on: str
    dimension: Dimension
    description: str
    notes: str
    version: int
    entity: str


@dataclass(frozen=True)
class Resolution:
    """What a set of requested filter terms resolved to, and what did not."""

    resolved: tuple[ResolvedTerm, ...]
    unresolved: tuple[str, ...]
    invalid: tuple[tuple[str, str], ...]

    @property
    def is_complete(self) -> bool:
        """True when at least one term resolved and none failed to.

        The caller must check this. A partial resolution assembled anyway is a
        query missing one of its filters, which returns more patients than were
        asked for and looks entirely plausible.

        `self.resolved` being non-empty is load-bearing, not a formality. With
        no requested terms at all the other two conditions are vacuously true,
        so an empty question would report itself complete and be refused by the
        assembler as "no predicates" — a rejection, when what actually happened
        is that the model could not identify a single term and should be asking
        the user.
        """
        return bool(self.resolved) and not self.unresolved and not self.invalid


@dataclass(frozen=True)
class MeasureResolution:
    """What a set of requested measures resolved to. Empty is legal here — the
    caller (an aggregate query needs at least one) is where that is enforced,
    because a dimension list is allowed to be empty and shares this shape."""

    resolved: tuple[ResolvedMeasure, ...]
    unresolved: tuple[str, ...]
    invalid: tuple[tuple[str, str], ...]

    @property
    def is_complete(self) -> bool:
        return not self.unresolved and not self.invalid


@dataclass(frozen=True)
class DimensionResolution:
    resolved: tuple[ResolvedDimension, ...]
    unresolved: tuple[str, ...]
    invalid: tuple[tuple[str, str], ...]

    @property
    def is_complete(self) -> bool:
        return not self.unresolved and not self.invalid


async def resolve_terms(session: AsyncSession, *, terms: Sequence[str]) -> Resolution:
    """Match requested filter terms against the definitions layer.

    Case- and whitespace-insensitive, matching a canonical term first and a
    synonym second. Exact matching only — no fuzzy fallback, deliberately: a
    near-miss that silently resolves to the wrong definition produces a
    confident answer to a question nobody asked. An unmatched term comes back
    in `unresolved` so the caller can ask rather than guess.
    """
    vocab = await load_vocabulary(session)
    resolved: list[ResolvedTerm] = []
    unresolved: list[str] = []
    invalid: list[tuple[str, str]] = []

    for requested in terms:
        definition = _lookup(vocab, "filter", requested)
        if definition is None:
            unresolved.append(requested)
            continue
        if definition.built is None:
            invalid.append((definition.term, definition.invalid_reason or "unusable"))
            continue
        resolved.append(
            ResolvedTerm(
                term=definition.term,
                matched_on=requested,
                predicate=cast("Predicate", definition.built),
                description=definition.description,
                notes=definition.notes,
                version=definition.version,
            )
        )

    return Resolution(
        resolved=tuple(resolved), unresolved=tuple(unresolved), invalid=tuple(invalid)
    )


async def resolve_measures(session: AsyncSession, *, names: Sequence[str]) -> MeasureResolution:
    """Match requested measure names against the definitions layer."""
    vocab = await load_vocabulary(session)
    resolved: list[ResolvedMeasure] = []
    unresolved: list[str] = []
    invalid: list[tuple[str, str]] = []

    for requested in names:
        definition = _lookup(vocab, "measure", requested)
        if definition is None:
            unresolved.append(requested)
            continue
        if definition.built is None:
            invalid.append((definition.term, definition.invalid_reason or "unusable"))
            continue
        resolved.append(
            ResolvedMeasure(
                term=definition.term,
                matched_on=requested,
                measure=cast("Measure", definition.built),
                description=definition.description,
                notes=definition.notes,
                version=definition.version,
            )
        )

    return MeasureResolution(
        resolved=tuple(resolved), unresolved=tuple(unresolved), invalid=tuple(invalid)
    )


async def resolve_dimensions(session: AsyncSession, *, names: Sequence[str]) -> DimensionResolution:
    """Match requested group-by names against the definitions layer."""
    vocab = await load_vocabulary(session)
    resolved: list[ResolvedDimension] = []
    unresolved: list[str] = []
    invalid: list[tuple[str, str]] = []

    for requested in names:
        definition = _lookup(vocab, "dimension", requested)
        if definition is None:
            unresolved.append(requested)
            continue
        if definition.built is None:
            invalid.append((definition.term, definition.invalid_reason or "unusable"))
            continue
        resolved.append(
            ResolvedDimension(
                term=definition.term,
                matched_on=requested,
                dimension=cast("Dimension", definition.built),
                description=definition.description,
                notes=definition.notes,
                version=definition.version,
                entity=definition.entity,
            )
        )

    return DimensionResolution(
        resolved=tuple(resolved), unresolved=tuple(unresolved), invalid=tuple(invalid)
    )


def _lookup(vocabulary: Vocabulary, kind: str, requested: str) -> Definition | None:
    definition = vocabulary.published_by_key.get(_normalise(requested))
    if definition is None or definition.kind != kind:
        return None
    return definition


# ------------------------------------------------------------------ CRUD


async def create_definition(  # noqa: PLR0913 — one keyword per column; see update_definition
    session: AsyncSession,
    *,
    term: str,
    kind: str,
    entity: str,
    description: str,
    logic: dict[str, Any],
    notes: str,
    synonyms: Sequence[str] = (),
    invariants: Sequence[dict[str, Any]] = (),
    status: str = "published",
    owner: str | None = None,
    changed_by: str,
    change_reason: str,
) -> ClinicalDefinition:
    """Add a definition. Validated the same way an edit is, and written with
    a `created` history row — a seeded definition and a curator's own carry
    the same guarantee.

    Validates shape and, for a leaf naming observation codes, checks them
    against `observation_catalog` — the same two-level check `load_vocabulary`
    applies. What is *not* checked here is whether a `term` reference inside
    this definition's own `logic` resolves, or whether an invariant's `term`
    names a real definition: both depend on the rest of the vocabulary and are
    re-verified on every `check_model()` call, the same way a dangling or
    cyclical `logic` reference surfaces there rather than here.
    """
    _require_one_of("kind", kind, KINDS)
    _require_one_of("entity", entity, ENTITIES)
    _require_one_of("status", status, STATUSES)
    built = validate_shape(kind, logic)
    parse_invariants(list(invariants))
    present = await _catalog_codes(session)
    _check_own_codes(term, kind, built, present)
    await _check_no_conflict(session, term=term, synonyms=synonyms, exclude_id=None)

    row = ClinicalDefinition(
        term=term,
        kind=kind,
        entity=entity,
        description=description,
        logic=logic,
        notes=notes,
        synonyms=list(synonyms),
        invariants=list(invariants),
        status=status,
        owner=owner,
        version=1,
        updated_by=changed_by,
    )
    session.add(row)
    await session.flush()
    session.add(
        ClinicalDefinitionHistory(
            definition_id=row.id,
            term=term,
            version=1,
            action="created",
            kind=kind,
            entity=entity,
            description=description,
            logic=logic,
            notes=notes,
            synonyms=list(synonyms),
            invariants=list(invariants),
            status=status,
            changed_by=changed_by,
            change_reason=change_reason,
        )
    )
    await session.commit()
    await session.refresh(row)
    invalidate()
    logger.info("clinical definition created", term=term, kind=kind, changed_by=changed_by)
    return row


async def update_definition(  # noqa: PLR0913 — every field is independently optional; a dataclass of Nones is not clearer
    session: AsyncSession,
    *,
    definition: ClinicalDefinition,
    kind: str | None = None,
    entity: str | None = None,
    description: str | None = None,
    logic: dict[str, Any] | None = None,
    notes: str | None = None,
    synonyms: Sequence[str] | None = None,
    invariants: Sequence[dict[str, Any]] | None = None,
    status: str | None = None,
    owner: str | None = None,
    changed_by: str,
    change_reason: str,
) -> ClinicalDefinition:
    """Change a definition. Every field is independently optional — pass only
    what changed — and every call bumps `version` and appends a history row,
    whether or not `logic` was the thing that moved. A rename is still a
    change someone should be able to attribute."""
    new_kind = kind if kind is not None else definition.kind
    new_entity = entity if entity is not None else definition.entity
    new_description = description if description is not None else definition.description
    new_logic = logic if logic is not None else definition.logic
    new_notes = notes if notes is not None else definition.notes
    new_synonyms = list(synonyms) if synonyms is not None else list(definition.synonyms)
    new_invariants = list(invariants) if invariants is not None else list(definition.invariants)
    new_status = status if status is not None else definition.status
    new_owner = owner if owner is not None else definition.owner

    _require_one_of("kind", new_kind, KINDS)
    _require_one_of("entity", new_entity, ENTITIES)
    _require_one_of("status", new_status, STATUSES)
    built = validate_shape(new_kind, new_logic)
    parse_invariants(new_invariants)
    present = await _catalog_codes(session)
    _check_own_codes(definition.term, new_kind, built, present)
    await _check_no_conflict(
        session, term=definition.term, synonyms=new_synonyms, exclude_id=definition.id
    )

    definition.kind = new_kind
    definition.entity = new_entity
    definition.description = new_description
    definition.logic = new_logic
    definition.notes = new_notes
    definition.synonyms = new_synonyms
    definition.invariants = new_invariants
    definition.status = new_status
    definition.owner = new_owner
    definition.version += 1
    definition.updated_by = changed_by

    await session.flush()
    session.add(
        ClinicalDefinitionHistory(
            definition_id=definition.id,
            term=definition.term,
            version=definition.version,
            action="updated",
            kind=new_kind,
            entity=new_entity,
            description=new_description,
            logic=new_logic,
            notes=new_notes,
            synonyms=new_synonyms,
            invariants=new_invariants,
            status=new_status,
            changed_by=changed_by,
            change_reason=change_reason,
        )
    )
    await session.commit()
    await session.refresh(definition)
    invalidate()
    logger.info(
        "clinical definition updated",
        term=definition.term,
        version=definition.version,
        changed_by=changed_by,
    )
    return definition


async def delete_definition(
    session: AsyncSession,
    *,
    definition: ClinicalDefinition,
    changed_by: str,
    change_reason: str,
) -> None:
    """Remove a definition. Not a soft delete: the row goes, and a final
    `deleted` history row — carrying what it said the moment before — is what
    survives it. Deliberately not FK'd to the row it describes, so this history
    stays readable after the row it is about is gone."""
    session.add(
        ClinicalDefinitionHistory(
            definition_id=definition.id,
            term=definition.term,
            version=definition.version,
            action="deleted",
            kind=definition.kind,
            entity=definition.entity,
            description=definition.description,
            logic=definition.logic,
            notes=definition.notes,
            synonyms=list(definition.synonyms),
            invariants=list(definition.invariants),
            status=definition.status,
            changed_by=changed_by,
            change_reason=change_reason,
        )
    )
    await session.delete(definition)
    await session.commit()
    invalidate()
    logger.info("clinical definition deleted", term=definition.term, changed_by=changed_by)


# -------------------------------------------------------------- model checks


@dataclass(frozen=True)
class ModelWarning:
    """One thing about the vocabulary worth a curator's attention.

    Not an error — the vocabulary still loads and still answers questions.
    This is the feedback loop AGENTS.md and SEMANTIC_LAYER.md both ask for:
    a term that cannot be built, and a filter that matches nobody in the
    loaded dataset, are both facts a definition's author would want to know
    without waiting for a clinician to notice.
    """

    term: str
    kind: str
    message: str


async def check_model(session: AsyncSession) -> list[ModelWarning]:
    """Warnings about the vocabulary as it stands against the loaded dataset.

    Two checks. First, every definition that failed to parse or resolve —
    `load_vocabulary` already computed this, so it costs nothing extra here.
    Second, for every published filter, whether it matches at least one
    patient — an empty threshold is exactly the failure a definitions layer is
    supposed to make visible instead of quietly returning nobody forever.

    Uses `app/clinical/assembler.patient_query` for the count, never the ORM
    models directly — this module is not on the allowlist in
    `test_only_the_assembler_queries_the_clinical_tables`, and it should not
    need to be for the same reason `catalog_service` needs to be: a warning
    about term coverage is not a clinical answer, but the row count under it
    still has to come from the one place that assembles a WHERE clause.
    """
    vocab = await load_vocabulary(session)
    warnings: list[ModelWarning] = [
        ModelWarning(term=definition.term, kind=definition.kind, message=definition.invalid_reason)
        for definition in vocab.definitions
        if definition.invalid_reason
    ]

    dataset = await session.scalar(
        select(DatasetMeta).order_by(DatasetMeta.loaded_at.desc()).limit(1)
    )
    if dataset is None:
        warnings.append(
            ModelWarning(term="(dataset)", kind="dataset", message="no dataset is loaded")
        )
        return warnings

    for definition in vocab.definitions:
        if (
            definition.kind != "filter"
            or definition.status != "published"
            or definition.built is None
        ):
            continue
        predicate = cast("Predicate", definition.built)
        try:
            rows = patient_query([predicate], today=dataset.as_of_date).subquery()
            count = await session.scalar(select(func.count()).select_from(rows))
        except InvalidPredicateError as error:
            warnings.append(ModelWarning(term=definition.term, kind="filter", message=str(error)))
            continue
        if not count:
            warnings.append(
                ModelWarning(
                    term=definition.term,
                    kind="filter",
                    message="matches no patient in the loaded dataset",
                )
            )

    warnings.extend(await _check_invariants(session, vocab, today=dataset.as_of_date))
    return warnings


async def _check_invariants(
    session: AsyncSession, vocab: Vocabulary, *, today: date
) -> list[ModelWarning]:
    """SEMANTIC_LAYER.md § 13's "these two terms must be disjoint" and "must
    be a subset of", checked against the loaded dataset rather than enforced
    at save time — the data under a threshold can shift, and this is a
    warning about that, the same way a definition matching nobody is.

    By exact term, not `published_by_key`'s synonym-inclusive lookup: an
    invariant names a specific definition, the same discipline
    `load_vocabulary`'s own `TermReference` resolution already follows.
    """
    by_term = {d.term: d for d in vocab.definitions}
    warnings: list[ModelWarning] = []

    for definition in vocab.definitions:
        if definition.kind != "filter" or definition.status != "published":
            continue
        for invariant in definition.invariants:
            other = by_term.get(invariant.term)
            if other is None:
                warnings.append(
                    ModelWarning(
                        term=definition.term,
                        kind="filter",
                        message=(
                            f"invariant references {invariant.term!r}, which is not a defined term"
                        ),
                    )
                )
                continue
            if other.kind != "filter" or other.built is None:
                warnings.append(
                    ModelWarning(
                        term=definition.term,
                        kind="filter",
                        message=f"invariant references {invariant.term!r}, not a usable filter",
                    )
                )
                continue

            this_ids = await _patient_ids(session, cast("Predicate", definition.built), today)
            other_ids = await _patient_ids(session, cast("Predicate", other.built), today)

            if invariant.type == "subset_of":
                offenders = this_ids - other_ids
                if offenders:
                    warnings.append(
                        ModelWarning(
                            term=definition.term,
                            kind="filter",
                            message=(
                                f"claims to be a subset of {invariant.term!r}, but "
                                f"{len(offenders)} matching patient(s) are not in it"
                            ),
                        )
                    )
            elif invariant.type == "disjoint_from":
                overlap = this_ids & other_ids
                if overlap:
                    warnings.append(
                        ModelWarning(
                            term=definition.term,
                            kind="filter",
                            message=(
                                f"claims to be disjoint from {invariant.term!r}, but "
                                f"{len(overlap)} patient(s) match both"
                            ),
                        )
                    )
    return warnings


async def _patient_ids(session: AsyncSession, predicate: Predicate, today: date) -> set[uuid.UUID]:
    """`patient_query`'s own default columns already include `id` — reading
    the attribute off each row is what keeps this module out of
    `test_only_the_assembler_queries_the_clinical_tables`'s allowlist, the
    same way the "matches nobody" check above already does not need to name
    `Patient` to count its rows."""
    result = await session.execute(patient_query([predicate], today=today))
    return {row.id for row in result}


# --------------------------------------------------------------- the checks


async def _catalog_codes(session: AsyncSession) -> frozenset[str]:
    result = await session.execute(select(ObservationCatalog.code))
    return frozenset(result.scalars().all())


def validate_shape(kind: str, logic: object) -> BuiltLogic:
    """Parse `logic` as the kind of definition it claims to be, or raise
    `InvalidPredicateError`. The one check a create, an update and a preview
    all run first."""
    if kind == "filter":
        return parse_predicate(logic)
    if kind == "measure":
        return parse_measure(logic)
    return parse_dimension(logic)


def _check_own_codes(term: str, kind: str, built: BuiltLogic, present: frozenset[str]) -> None:
    """Codes named directly in this definition's own `logic` — not through a
    `term` reference, which is checked when the referenced definition itself
    was created."""
    if kind == "filter":
        _check_codes(term, observation_codes(cast("Predicate", built)), present)
    elif kind == "measure" and isinstance(built, ObservationAggregate):
        _check_codes(term, ((built.codes, built.units),), present)


def _check_codes(
    term: str,
    pairs: Sequence[tuple[tuple[str, ...], tuple[str, ...]]],
    present: frozenset[str],
) -> None:
    """A definition naming observation codes must name at least one the
    dataset actually has, or it would match nobody forever and look like a
    clean empty answer. Partial coverage is expected and only logged — a code
    set is the union of the spellings different exports use."""
    for codes, _units in pairs:
        found = [code for code in codes if code in present]
        missing = [code for code in codes if code not in present]
        if not found:
            message = (
                f"none of the codes {list(codes)} for term {term!r} appear in the loaded "
                "dataset; this term would match nobody"
            )
            raise InvalidPredicateError(message)
        if missing:
            logger.info(
                "definition codes partially present", term=term, present=found, absent=missing
            )


async def _check_no_conflict(
    session: AsyncSession, *, term: str, synonyms: Sequence[str], exclude_id: uuid.UUID | None
) -> None:
    """No other definition may claim this term or any of these synonyms.

    With exact matching and no fuzzy fallback, two rows claiming the same
    spelling resolves to whichever is found first — arbitrary and invisible.
    Refusing the write is cheaper than discovering it from a wrong answer.
    """
    target = {_normalise(term), *(_normalise(s) for s in synonyms)}
    rows = await list_definitions(session, include_unpublished=True)
    for row in rows:
        if exclude_id is not None and row.id == exclude_id:
            continue
        existing = {_normalise(row.term), *(_normalise(s) for s in row.synonyms)}
        overlap = sorted(target & existing)
        if overlap:
            message = (
                f"{overlap} already claimed by definition {row.term!r}; a term or synonym "
                "may only mean one thing"
            )
            raise DefinitionConflictError(message)


def _require_one_of(field: str, value: str, allowed: tuple[str, ...]) -> None:
    if value not in allowed:
        message = f"{field} must be one of {list(allowed)}, got {value!r}"
        raise InvalidPredicateError(message)


def _normalise(value: str) -> str:
    return " ".join(value.lower().split())
