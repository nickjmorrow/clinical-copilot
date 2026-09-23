"""The HTTP response envelope, the request bodies, and the HTTP-only resources.

**Every response is `{"data": ..., "meta": ...}`.** A bare array or scalar at the
top level leaves nowhere to add pagination, warnings, or a deprecation notice
without breaking clients.

What is *not* here is the event vocabulary: that lives in `app/wire.py`, because
the worker publishes the same event shapes onto the bus that this layer returns
over HTTP, and a process that serves no requests should not have to import the
HTTP layer to say what an event looks like. The shapes below are the ones that
genuinely only travel over HTTP — a request body, a response envelope, a
conversation resource — and they inherit camelCase from `wire.ApiSchema` along
with everything else on the wire.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.config import settings
from app.models import ClinicalDefinition, ClinicalDefinitionHistory, Conversation, Task
from app.services.audit_service import UnresolvedTermEntry
from app.services.catalog_service import Catalog, DatasetProvenance
from app.services.clinical_query_service import BrowseResult, ClinicalAnswer
from app.services.definition_service import ModelWarning
from app.wire import ApiSchema, EventOut, to_event_out


class Meta(ApiSchema):
    status: Literal["success"] = "success"


class ApiResponse[T](BaseModel):
    data: T
    meta: Meta = Meta()


# ---------------------------------------------------------------- resources


class DefinedTermOut(ApiSchema):
    """One clinical term, as a reader needs to see it.

    Carries `notes` because the justification is the point — a threshold a
    reader cannot interrogate is one they have to take on trust. Deliberately
    omits `logic`: that is the assembler's business, and rendering a predicate
    invites a reader to reason about the number instead of the name. `kind`
    tells a reader whether this is something to filter on, aggregate, or
    group by — the same three the model's tool understands.
    """

    term: str
    kind: str
    means: str
    also_called: list[str]
    why: str


class DatasetProvenanceOut(ApiSchema):
    """Where the loaded data came from, and what "today" means for it.

    SEMANTIC_LAYER.md § 1: every age and every "currently prescribed" in
    every answer is relative to `as_of_date`, and that is silently wrong to a
    reader who cannot see it.
    """

    source: str
    as_of_date: date
    patient_count: int
    notes: str | None
    loaded_at: datetime


class ObservationCatalogEntryOut(ApiSchema):
    code: str
    display: str
    category: str | None
    unit: str | None
    units: list[str]
    observation_count: int
    patient_count: int
    is_numeric: bool


class DatasetOut(ApiSchema):
    dataset: DatasetProvenanceOut | None
    patients: int
    medications: int
    prescriptions: int
    observations: int
    observation_catalog: list[ObservationCatalogEntryOut]
    annotation_values: dict[str, list[str]]
    returnable_columns: list[str]
    restricted_columns: list[str]
    max_rows: int


class ClinicalContextOut(ApiSchema):
    terms: list[DefinedTermOut]
    dataset: DatasetOut


def to_dataset_provenance_out(dataset: DatasetProvenance | None) -> DatasetProvenanceOut | None:
    """Shared by every response that cites where its rows came from — the
    context panel, a cohort or aggregate answer, a browsed page. One
    conversion rather than the same ternary at each call site."""
    if dataset is None:
        return None
    return DatasetProvenanceOut(
        source=dataset.source,
        as_of_date=dataset.as_of_date,
        patient_count=dataset.patient_count,
        notes=dataset.notes,
        loaded_at=dataset.loaded_at,
    )


def to_clinical_context(
    definitions: list[ClinicalDefinition], catalog: Catalog
) -> ClinicalContextOut:
    return ClinicalContextOut(
        terms=[
            DefinedTermOut(
                term=definition.term,
                kind=definition.kind,
                means=definition.description,
                also_called=[str(s) for s in definition.synonyms],
                why=definition.notes,
            )
            for definition in definitions
        ],
        dataset=DatasetOut(
            dataset=to_dataset_provenance_out(catalog.dataset),
            patients=catalog.patients,
            medications=catalog.medications,
            prescriptions=catalog.prescriptions,
            observations=catalog.observations,
            observation_catalog=[
                ObservationCatalogEntryOut(
                    code=entry.code,
                    display=entry.display,
                    category=entry.category,
                    unit=entry.unit,
                    units=list(entry.units),
                    observation_count=entry.observation_count,
                    patient_count=entry.patient_count,
                    is_numeric=entry.is_numeric,
                )
                for entry in catalog.observation_catalog
            ],
            annotation_values={
                attribute: list(values) for attribute, values in catalog.annotation_values.items()
            },
            returnable_columns=list(catalog.returnable_columns),
            restricted_columns=list(catalog.restricted_columns),
            max_rows=catalog.max_rows,
        ),
    )


# --------------------------------------------------- the authoring surface
#
# SEMANTIC_LAYER.md § 2: a model view separate from the chat panel, that shows
# `logic` — which `ClinicalContextOut` above deliberately withholds. Readable
# by anyone (see `api/routes/definitions.py`); the model never sees any of
# this.


class DefinitionOut(ApiSchema):
    id: UUID
    term: str
    kind: str
    entity: str
    description: str
    logic: dict[str, Any]
    notes: str
    synonyms: list[str]
    invariants: list[dict[str, Any]]
    status: str
    owner: str | None
    reviewed_at: datetime | None
    version: int
    updated_by: str | None
    created_at: datetime
    updated_at: datetime


def to_definition_out(definition: ClinicalDefinition) -> DefinitionOut:
    return DefinitionOut.model_validate(definition)


class DefinitionHistoryOut(ApiSchema):
    id: UUID
    definition_id: UUID
    term: str
    version: int
    action: str
    kind: str
    entity: str
    description: str
    logic: dict[str, Any]
    notes: str
    synonyms: list[str]
    invariants: list[dict[str, Any]]
    status: str
    changed_by: str
    change_reason: str
    created_at: datetime


def to_definition_history_out(row: ClinicalDefinitionHistory) -> DefinitionHistoryOut:
    return DefinitionHistoryOut.model_validate(row)


class ModelWarningOut(ApiSchema):
    term: str
    kind: str
    message: str


def to_model_warning_out(warning: ModelWarning) -> ModelWarningOut:
    return ModelWarningOut(term=warning.term, kind=warning.kind, message=warning.message)


class DefinitionPreviewOut(ApiSchema):
    """How many patients a *proposed* filter's predicate would match —
    SEMANTIC_LAYER.md § 6. `null` for a measure or a dimension: neither has a
    cohort of its own to preview, and the request having validated at all
    (a 422 otherwise) is the whole answer for those two kinds."""

    patient_count: int | None


class ConversationOut(ApiSchema):
    id: UUID
    title: str | None
    # Timestamps rather than `pinned: bool`, because the client needs the order
    # as well as the fact — pinned conversations sort by when they were pinned.
    # `archivedAt` travels for the same reason the row does: the archived list
    # is a real view, not an absence.
    pinned_at: datetime | None
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


class TaskOut(ApiSchema):
    id: UUID
    kind: Literal["chat_turn", "agent_run"]
    status: Literal["pending", "running", "succeeded", "failed", "cancelled", "superseded"]
    created_at: datetime


class ConversationDetailOut(ConversationOut):
    events: list[EventOut]
    # Present when work is still in flight. This is what tells a page that just
    # loaded to reattach to the stream instead of assuming the transcript is
    # finished — the whole point of refresh-and-pick-up-where-you-were.
    active_task: TaskOut | None = None


class SendMessageOut(ApiSchema):
    """Sending no longer returns an answer, it returns a receipt.

    `seq` is where the caller should resume the stream from: it has the user's
    own message already, and wants everything after it.
    """

    task_id: UUID
    seq: int


class ScheduleOut(ApiSchema):
    id: UUID
    name: str
    prompt: str
    interval_seconds: int
    enabled: bool
    next_run_at: datetime
    created_at: datetime


class SavedQuestionOut(ApiSchema):
    id: UUID
    name: str
    terms: list[str]
    measures: list[str]
    group_by: list[str]
    created_at: datetime


class ResolvedTermOut(ApiSchema):
    """One resolved filter, measure, or dimension — trimmed to what a saved
    question's re-run needs to show its working, the same reason `find_patients`
    puts these two fields in the rendered answer rather than just a count."""

    term: str
    description: str
    notes: str


class UnmeasuredOut(ApiSchema):
    term: str
    count: int


class SavedQuestionRunOut(ApiSchema):
    """Re-running a saved question, right now — never stored. Mirrors
    `ClinicalAnswer` in `clinical_query_service.py`, minus `executed_sql`
    (the audit row's business, not a caller's) and the `vocabulary` fallback a
    fresh clarification carries: a saved question was resolvable when it was
    saved, so the only way `outcome` is not `"answered"` here is a definition
    changing or disappearing underneath it, which is itself worth surfacing
    plainly rather than dressed up as a first-time clarification."""

    outcome: str
    aggregate: bool
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool
    resolved_terms: list[ResolvedTermOut]
    resolved_measures: list[ResolvedTermOut]
    resolved_dimensions: list[ResolvedTermOut]
    unmeasured: list[UnmeasuredOut]
    dataset: DatasetProvenanceOut | None
    reason: str | None
    unresolved: list[str]


def _json_safe(value: object) -> object:
    """`rows` is typed `dict[str, Any]` because its keys are term names, not a
    fixed schema — which means Pydantic never learns a `Decimal` value (an
    average eGFR, straight off a Postgres NUMERIC) is a number, and serializes
    it as a *string* rather than refusing it outright. `float()` here is what
    makes `"average eGFR": "11.8"` a JSON number instead — the same fix, and
    the same reason, as `_json_safe` in `app/tools/find_patients.py`.
    """
    return float(value) if isinstance(value, Decimal) else value


def to_saved_question_run_out(answer: ClinicalAnswer) -> SavedQuestionRunOut:
    return SavedQuestionRunOut(
        outcome=answer.outcome,
        aggregate=answer.aggregate,
        columns=list(answer.columns),
        rows=[{key: _json_safe(value) for key, value in row.items()} for row in answer.rows],
        row_count=answer.row_count,
        truncated=answer.truncated,
        resolved_terms=[
            ResolvedTermOut(term=r.term, description=r.description, notes=r.notes)
            for r in answer.resolved
        ],
        resolved_measures=[
            ResolvedTermOut(term=r.term, description=r.description, notes=r.notes)
            for r in answer.resolved_measures
        ],
        resolved_dimensions=[
            ResolvedTermOut(term=r.term, description=r.description, notes=r.notes)
            for r in answer.resolved_dimensions
        ],
        unmeasured=[UnmeasuredOut(term=u.term, count=u.count) for u in answer.unmeasured],
        dataset=to_dataset_provenance_out(answer.dataset),
        reason=answer.reason,
        unresolved=list(answer.unresolved),
    )


class AccessOut(ApiSchema):
    """One user's roles and row-level scope — SEMANTIC_LAYER.md § 19.

    `available_states` rides along so the client has real values to offer
    rather than a guessed list of fifty; see
    `catalog_service.list_patient_states`.
    """

    user_id: str
    roles: list[str]
    scope_states: list[str] | None
    available_states: list[str]


def to_conversation_detail(
    conversation: Conversation, *, active_task: Task | None = None
) -> ConversationDetailOut:
    return ConversationDetailOut(
        id=conversation.id,
        title=conversation.title,
        pinned_at=conversation.pinned_at,
        archived_at=conversation.archived_at,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        events=[e for e in (to_event_out(r) for r in conversation.events) if e is not None],
        active_task=TaskOut.model_validate(active_task) if active_task is not None else None,
    )


# ---------------------------------------------------------------- requests


class SendMessageIn(ApiSchema):
    # Bounded here rather than left to the model. An unbounded body is unbounded
    # tokens, and the limit you picked on purpose is better than the one the
    # provider happens to enforce — this one produces a 422 the client can show,
    # not a truncated answer and a bill.
    content: str = Field(max_length=settings.max_message_length)


class ConversationUpdateIn(ApiSchema):
    """A patch: every field optional, and absent is not the same as null.

    Which is why the route reads `model_fields_set` rather than testing for
    None. `{"pinned": false}` and `{}` both arrive with `pinned is None` here,
    and they mean opposite things — unpin, versus do not touch the pin.
    """

    title: str | None = Field(default=None, max_length=200)
    pinned: bool | None = None
    archived: bool | None = None


class ScheduleIn(ApiSchema):
    name: str = Field(max_length=200)
    prompt: str = Field(max_length=settings.max_message_length)
    interval_seconds: int = Field(ge=60)


class SavedQuestionCreateIn(ApiSchema):
    name: str = Field(min_length=1, max_length=200)
    terms: list[str] = Field(min_length=1)
    measures: list[str] = Field(default_factory=list)
    group_by: list[str] = Field(default_factory=list)


class CohortQueryIn(ApiSchema):
    """An ad-hoc cohort or aggregate query — SEMANTIC_LAYER.md § 3's cohort
    drilldown, in request-body form. Unlike `SavedQuestionCreateIn`, this asks
    once and does not persist anything; `columns` is the one field a saved
    question does not have, because "every returnable column, not just the
    three the model asked for" is the whole reason to reach for this."""

    terms: list[str] = Field(min_length=1)
    measures: list[str] = Field(default_factory=list)
    group_by: list[str] = Field(default_factory=list)
    columns: list[str] = Field(default_factory=list)


class AccessUpdateIn(ApiSchema):
    """`None` clears the scope — unconfined, same meaning as no row at all.
    Roles are deliberately not editable here: granting yourself a role is a
    different, more sensitive act than choosing which states your own
    queries are confined to, and this form is only for the second one."""

    scope_states: list[str] | None


class DefinitionCreateIn(ApiSchema):
    term: str = Field(min_length=1, max_length=200)
    kind: Literal["filter", "measure", "dimension"]
    entity: Literal["patient", "medication", "observation"]
    description: str = Field(min_length=1)
    logic: dict[str, Any]
    notes: str = Field(min_length=1)
    synonyms: list[str] = Field(default_factory=list)
    invariants: list[dict[str, Any]] = Field(default_factory=list)
    # Draft, not published — unlike the seed's default. A term typed into the
    # editor has not been reviewed yet; the seed's vocabulary is trusted at
    # load time because it went through this same path once, by hand, before
    # any of it existed. See `DefinitionPublishIn` for the explicit step that
    # moves a draft live.
    status: Literal["draft", "published", "deprecated"] = "draft"
    owner: str | None = None
    change_reason: str = Field(min_length=1)


class DefinitionUpdateIn(ApiSchema):
    """A patch. Every field but `change_reason` is optional and absent means
    unchanged — `definition_service.update_definition` already treats `None`
    this way for each of these, so there is no separate absent-vs-null
    distinction to make here the way there is on `ConversationUpdateIn`."""

    kind: Literal["filter", "measure", "dimension"] | None = None
    entity: Literal["patient", "medication", "observation"] | None = None
    description: str | None = Field(default=None, min_length=1)
    logic: dict[str, Any] | None = None
    notes: str | None = Field(default=None, min_length=1)
    synonyms: list[str] | None = None
    invariants: list[dict[str, Any]] | None = None
    status: Literal["draft", "published", "deprecated"] | None = None
    owner: str | None = None
    change_reason: str = Field(min_length=1)


class ChangeReasonIn(ApiSchema):
    """The one field `publish` and `delete` both need and nothing else —
    every write to a definition is required to say why, including the ones
    that change no other field."""

    change_reason: str = Field(min_length=1)


class DefinitionPreviewIn(ApiSchema):
    """A proposed `logic`, not yet saved anywhere. `kind` says which parser
    validates it — a preview must work for a measure or a dimension being
    edited too, even though only a filter's preview returns a patient count."""

    kind: Literal["filter", "measure", "dimension"]
    logic: dict[str, Any]


class UnresolvedTermOut(ApiSchema):
    """One question the system could not resolve, ranked by how often it has
    come up — SEMANTIC_LAYER.md § 14: the backlog for what to define next."""

    raw_question: str
    count: int
    last_asked: datetime
    asked_by: list[str]


def to_unresolved_term_out(entry: UnresolvedTermEntry) -> UnresolvedTermOut:
    return UnresolvedTermOut(
        raw_question=entry.raw_question,
        count=entry.count,
        last_asked=entry.last_asked,
        asked_by=list(entry.asked_by),
    )


class BrowsePageOut(ApiSchema):
    """One page of the raw patient table — SEMANTIC_LAYER.md § 3's governed
    table browser. `total` is the whole scoped population, not this page's
    size, so the frontend can render "page 3 of 40" rather than just what it
    was handed."""

    outcome: str
    columns: list[str]
    rows: list[dict[str, Any]]
    total: int
    offset: int
    limit: int
    dataset: DatasetProvenanceOut | None
    reason: str | None


def to_browse_page_out(result: BrowseResult) -> BrowsePageOut:
    return BrowsePageOut(
        outcome=result.outcome,
        columns=list(result.columns),
        rows=[{key: _json_safe(value) for key, value in row.items()} for row in result.rows],
        total=result.total,
        offset=result.offset,
        limit=result.limit,
        dataset=to_dataset_provenance_out(result.dataset),
        reason=result.reason,
    )
