"""ORM models.

**This file is the source of truth for the schema.** Alembic autogenerates
migrations by diffing these classes against the database, so anything not
declared here does not exist: a CHECK constraint left out is a CHECK constraint
dropped, silently, on the next `alembic revision --autogenerate`.

That is why the constraints below are spelled out rather than left to the
service layer to enforce. The application validates too — better errors, closer
to the user — but the database is the thing that cannot be bypassed by a
migration script, a psql session, or the next process someone writes.

Note `default=` AND `server_default=` on several columns. They are not
redundant: `default=` is applied by SQLAlchemy when the ORM inserts a row, and
`server_default=` is what the column actually has in Postgres. Declare only the
first and every insert that does not go through the ORM — a psql session, a
fixture, the raw SQL in task_service — hits a NOT NULL column with no default.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    desc,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

# N811: `UUID` is a class, not a constant — pep8-naming cannot tell.
from sqlalchemy.dialects.postgresql import UUID as PgUUID  # noqa: N811 — see above
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The user named this one, so nothing may rename it. Auto-naming reads this
    # and stops; without it a rename typed during the first turn is silently
    # overwritten the moment that turn finishes.
    title_custom: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    # Timestamps rather than booleans, for both of these. `pinned_at` is also
    # the order pinned conversations appear in, and `archived_at` answers "when
    # did this leave the list" — which a boolean throws away for no saving.
    pinned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    events: Mapped[list["EventRecord"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="EventRecord.seq",
    )

    __table_args__ = (
        # DESC matters: the list query is "newest first", and an ascending index
        # can serve it only by scanning backwards.
        #
        # Partial, because every list request adds `archived_at is null` and an
        # archive is meant to be the pile you stop paying for. Rows leaving the
        # index on archive is the point, not a side effect.
        Index(
            "conversations_user_updated_idx",
            "user_id",
            desc("updated_at"),
            postgresql_where=text("archived_at is null"),
        ),
    )


class EventRecord(Base):
    """One thing that happened, in order. Append-only — nothing updates a row.

    CONVENTIONS.md > The transcript says why the transcript is an event log
    rather than a messages table; `app/wire.py` reads `data` per `type`.
    """

    __tablename__ = "event_records"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    # bigserial in the schema. FetchedValue tells SQLAlchemy "the database fills
    # this in" so it is left out of the INSERT and read back afterwards.
    # An identity column. Postgres assigns it, which is what makes it a
    # reliable total order — and Alembic can emit it, which FetchedValue could
    # not: that only told SQLAlchemy "someone else fills this in".
    seq: Mapped[int] = mapped_column(BigInteger, Identity(), nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    conversation: Mapped[Conversation] = relationship(back_populates="events")

    __table_args__ = (
        CheckConstraint(
            "type in ('user_message', 'assistant_message', 'tool_call', 'tool_result')",
            name="event_records_type_check",
        ),
        Index("event_records_conversation_seq_idx", "conversation_id", "seq"),
    )


class Task(Base):
    """One unit of work a worker will pick up.

    Mutable, unlike EventRecord — this is the state of work in progress, not a
    record of what happened. CONVENTIONS.md > The worker says why Postgres is the
    queue.
    """

    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=True
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default="pending", server_default=text("'pending'")
    )
    run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    cancel_requested: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3, server_default=text("3")
    )
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    claimed_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The request that enqueued this, so the worker's logs can be joined to the
    # API's. Null for anything the worker enqueued itself, like a scheduled run.
    request_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("kind in ('chat_turn', 'agent_run')", name="tasks_kind_check"),
        CheckConstraint(
            "status in ('pending', 'running', 'succeeded', 'failed', 'cancelled', 'superseded')",
            name="tasks_status_check",
        ),
        # Partial, because the claim query only ever looks at pending rows.
        # Without postgresql_where this becomes a full index over every task
        # that has ever run, which is the opposite of the point.
        Index("tasks_claim_idx", "run_at", postgresql_where=text("status = 'pending'")),
        Index("tasks_conversation_idx", "conversation_id", desc("created_at")),
    )


class Schedule(Base):
    """A prompt plus a cadence. The worker expands due rows into agent_run tasks."""

    __tablename__ = "schedules"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    next_run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("interval_seconds >= 60", name="schedules_interval_check"),
        Index("schedules_due_idx", "next_run_at", postgresql_where=text("enabled")),
    )


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
# The clinical dataset
#
# Loaded from Synthea, MITRE's open-source synthetic patient simulator. Every
# row is fabricated by a published generator rather than invented here, which
# matters for a reason beyond realism: Synthea emits real coding systems, and
# real coding systems are what force the query layer to stop assuming this
# particular dataset.
#
# Three consequences run through the tables below.
#
# **Codes, not names.** An observation is LOINC `33914-3`, not the string
# "egfr". A medication is RxNorm, not "gentamicin". Nothing in `app/clinical/`
# may hard-code one.
#
# **An analyte has more than one code.** Creatinine arrives as both `2160-0`
# (serum) and `38483-4` (blood); potassium as `2823-3` and `6298-4`. A
# definition that matches a single code silently misses half its patients, so
# terms resolve to code *sets*.
#
# **Clinical judgement is not in the source data.** Synthea says a patient was
# prescribed RxNorm 1719286; it does not say that is nephrotoxic. That
# annotation is curated, which is correct — it is what a hospital's own
# formulary review produces — and it lives in `medication_annotations`, keyed
# by code, rather than in a column invented on the drug table.
# --------------------------------------------------------------------------


class DatasetMeta(Base):
    """Which dataset is loaded, and when it thinks "now" is.

    A generated cohort is frozen in time: its newest encounter is whenever the
    generator stopped. Computing age from the wall clock instead would make
    every age-dependent answer drift away from the data as months pass, and
    would make "over 65" mean something different in March than it did in
    September.

    So `as_of_date` is the dataset's own today, derived on load from the latest
    record in it, and every age and recency comparison is made against this.
    """

    __tablename__ = "dataset_meta"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    source: Mapped[str] = mapped_column(Text, nullable=False)
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    patient_count: Mapped[int] = mapped_column(Integer, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    loaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Patient(Base):
    """A synthetic patient, as Synthea describes one.

    The identifiers are stored rather than dropped on load, and there are more
    of them than the hand-rolled schema had: Synthea issues an SSN, a driving
    licence and a passport number alongside a name and a birth date. Keeping
    them is the point — a column-level access rule that works because the
    sensitive column was never loaded proves nothing. `app/clinical/columns.py`
    is what keeps them out of an answer.
    """

    __tablename__ = "patients"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    # Synthea's own patient id. The stable handle across a reload, and the
    # identifier an answer refers a patient by — the equivalent of an MRN, and
    # restricted for the same reasons an MRN would be.
    source_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    birth_date: Mapped[date] = mapped_column(Date, nullable=False)
    death_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    sex: Mapped[str] = mapped_column(Text, nullable=False)
    race: Mapped[str | None] = mapped_column(Text, nullable=True)
    ethnicity: Mapped[str | None] = mapped_column(Text, nullable=True)
    state: Mapped[str | None] = mapped_column(Text, nullable=True)
    city: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Direct identifiers. Loaded, never returned.
    ssn: Mapped[str | None] = mapped_column(Text, nullable=True)
    drivers: Mapped[str | None] = mapped_column(Text, nullable=True)
    passport: Mapped[str | None] = mapped_column(Text, nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("sex in ('female', 'male', 'other', 'unknown')", name="patients_sex_check"),
        Index("patients_birth_date_idx", "birth_date"),
    )


class Medication(Base):
    """A drug, as the source coded it. Nothing clinical is asserted here.

    Deliberately thin. The hand-rolled version of this table carried a
    `nephrotoxic_risk` column, which was a judgement stored as though it were a
    fact about the drug. Synthea makes the distinction unavoidable: it supplies
    an RxNorm code and a display name and knows nothing about kidney risk.

    The judgement lives in `medication_annotations`.
    """

    __tablename__ = "medications"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    code: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    system: Mapped[str] = mapped_column(Text, nullable=False)
    display: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("medications_code_idx", "code"),)


class MedicationAnnotation(Base):
    """Curated clinical judgement about a drug, keyed by code.

    **This table is the honest home for everything the source data does not
    say.** "Vancomycin is a high nephrotoxic risk" is not a fact Synthea
    supplies; it is a review decision, of the kind a hospital's own formulary
    committee records, and it is reviewable precisely because it is a row with
    a rationale rather than a column someone once set.

    Keyed by `code` and not by a foreign key to `medications.id`, so the
    annotations survive a reload of the dataset. Reference knowledge about
    drugs should not be destroyed by reimporting patients.

    `attribute` is open rather than an enum: `nephrotoxic_risk` is the one this
    project uses, and adding `qt_prolonging` should be a row, not a migration.
    """

    __tablename__ = "medication_annotations"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    code: Mapped[str] = mapped_column(Text, nullable=False)
    system: Mapped[str] = mapped_column(Text, nullable=False)
    attribute: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    # Why this drug carries this value. NOT NULL for the same reason
    # clinical_definitions.notes is: an unexplained judgement is the thing this
    # table exists to prevent.
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("code", "attribute", name="medication_annotations_code_attribute_key"),
        CheckConstraint(
            "length(trim(rationale)) > 0", name="medication_annotations_rationale_check"
        ),
        Index("medication_annotations_attribute_idx", "attribute", "value"),
    )


class Prescription(Base):
    """A patient on a drug, over a period.

    `end_date is null` means the prescription is open. It does NOT reliably
    mean "currently taking": whether a generator closes a finished course is a
    property of the export, and two Synthea releases disagree about it. That is
    exactly why exposure is a choice a definition makes rather than a rule the
    query layer imposes — see `MedicationAttribute` in app/clinical/predicates.py.
    """

    __tablename__ = "prescriptions"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("patients.id", ondelete="CASCADE"), nullable=False
    )
    medication_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("medications.id", ondelete="RESTRICT"), nullable=False
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    reason_display: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "end_date is null or end_date >= start_date", name="prescriptions_date_order_check"
        ),
        Index("prescriptions_patient_idx", "patient_id"),
        Index("prescriptions_medication_idx", "medication_id"),
        # Recency questions ("ended within two years") scan by end date.
        Index("prescriptions_end_date_idx", "end_date"),
    )


class Observation(Base):
    """One coded measurement, at one time. Was `labs`.

    Renamed and re-keyed because the shape changed in a way the old name hid:
    `test_name` was a string this project chose, and `code` is an identifier the
    world agrees on. The rename is what makes the difference visible in every
    file that touches it.

    Values arrive as text from Synthea and are split here: `value_numeric` for
    anything a threshold can compare, `value_text` for the rest. A threshold
    predicate reads only the numeric column, so a qualitative result can never
    be silently coerced into a comparison.
    """

    __tablename__ = "observations"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("patients.id", ondelete="CASCADE"), nullable=False
    )
    # Synthea's own grouping — laboratory, vital-signs, survey — kept because
    # it is the cheapest honest answer to "is this a measurement or a
    # questionnaire score", which the catalog otherwise cannot tell.
    category: Mapped[str | None] = mapped_column(Text, nullable=True)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    system: Mapped[str] = mapped_column(Text, nullable=False)
    display: Mapped[str] = mapped_column(Text, nullable=False)
    value_numeric: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    value_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    unit: Mapped[str | None] = mapped_column(Text, nullable=True)
    taken_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "value_numeric is not null or value_text is not null",
            name="observations_has_a_value_check",
        ),
        # DESC on taken_at: every threshold question is "their latest X", which
        # this index answers without a sort.
        Index("observations_patient_code_taken_idx", "patient_id", "code", desc("taken_at")),
        Index("observations_code_idx", "code"),
    )


class ObservationCatalog(Base):
    """Which codes are actually present, and how often.

    The validator checks a definition's codes against this rather than against
    a tuple in Python. That is most of what "not coupled to the dataset" means
    here: load a different cohort and the set of answerable measurements
    changes with it, without a code change or a migration.

    Also what the vocabulary panel reports as available, and what makes a
    definition referencing a code nobody measured a loud failure at load rather
    than an empty answer at query time.
    """

    __tablename__ = "observation_catalog"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    code: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    system: Mapped[str] = mapped_column(Text, nullable=False)
    display: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The commonest unit, for display; `units` is every unit this code was
    # seen in, which is what a definition's declared units are checked against.
    unit: Mapped[str | None] = mapped_column(Text, nullable=True)
    units: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    observation_count: Mapped[int] = mapped_column(Integer, nullable=False)
    patient_count: Mapped[int] = mapped_column(Integer, nullable=False)
    is_numeric: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ClinicalDefinition(Base):
    """A clinical term, and the logic it resolves to.

    **This table is the architectural bet.** Without it the model is asked to
    invent "impaired renal function" per question, and the threshold drifts
    between answers with nothing to point at. With it, the model's job shrinks
    to picking the right term, and the threshold is written once, reviewable,
    and cited in the answer.

    `logic` is a structured predicate, not a SQL fragment. That is deliberate:
    a table of SQL snippets that get interpolated into a query is an injection
    vector wearing a config table's clothes, and it also cannot be validated.
    A JSONB spec can be checked against an allowlist of shapes before anything
    is assembled, and the assembler stays the only thing that writes SQL.

    Shapes the assembler understands (see the query layer for the validator):

        {"type": "observation_threshold", "codes": ["33914-3"],
         "operator": "<", "value": 60, "most_recent": true}

        {"type": "medication_attribute", "attribute": "nephrotoxic_risk",
         "in": ["high", "moderate"], "exposure": "recent", "within_days": 730}

        {"type": "age_threshold", "operator": ">=", "value": 65}

    `codes` is a list because an analyte has more than one code in real data —
    creatinine arrives as both LOINC 2160-0 and 38483-4 — and a term matching
    only one of them silently misses half its patients.

    `exposure` is stated rather than assumed. Whether a finished course is
    closed at all is a property of the export, so "currently on this drug" is a
    claim a definition makes, with its reasoning in `notes`, instead of a rule
    the query layer imposes on every dataset.
    """

    __tablename__ = "clinical_definitions"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    term: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    # What the term selects, which tells the assembler where the predicate goes.
    entity: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    logic: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    # Why this threshold and not another one, with its source. NOT NULL because
    # an undefended threshold is the thing this whole table exists to prevent.
    notes: Mapped[str] = mapped_column(Text, nullable=False)
    # Synonyms the model may map a question onto — "low kidney function",
    # "renal impairment", "CKD". Matching happens in the query layer; this is
    # the vocabulary it matches against.
    synonyms: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # A filter's claimed relationship to another filter — `[{"type":
    # "subset_of", "term": "impaired renal function"}]` — checked against the
    # loaded dataset by `definition_service.check_model()`, the same way a
    # definition matching nobody is: a warning, not a rejection, because the
    # data can change under a threshold that was true when it was written.
    # SEMANTIC_LAYER.md § 13's "these two terms must be disjoint" in schema
    # form. Empty for every kind but `filter`; nothing stops a measure or
    # dimension from carrying one, but nothing checks it either.
    invariants: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # What kind of thing this row defines. A `filter` selects patients; a
    # `measure` aggregates over them; a `dimension` groups them. All three are
    # rows here rather than three tables because they share everything that
    # matters — a term, a justification, a structured `logic`, a history — and
    # the model picks from all three by name the same way.
    kind: Mapped[str] = mapped_column(
        Text, nullable=False, default="filter", server_default=text("'filter'")
    )
    # Only `published` rows reach the model's vocabulary. A draft is something a
    # curator is still arguing with; a deprecated term stays so old answers can
    # still be read back against it, but nothing new resolves to it.
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default="published", server_default=text("'published'")
    )
    # Who stands behind this definition, and when they last said so. Cheap
    # columns that mean nothing for seven rows written in one sitting and are
    # the whole of "certified" once several people edit seventy of them.
    owner: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Bumped on every edit, and recorded on every answer that resolved through
    # this row. That is what lets an answer from last month say which threshold
    # it used, rather than which one exists today.
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
    updated_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "entity in ('patient', 'medication', 'observation')",
            name="clinical_definitions_entity_check",
        ),
        CheckConstraint(
            "kind in ('filter', 'measure', 'dimension')", name="clinical_definitions_kind_check"
        ),
        CheckConstraint(
            "status in ('draft', 'published', 'deprecated')",
            name="clinical_definitions_status_check",
        ),
        CheckConstraint("version >= 1", name="clinical_definitions_version_check"),
        CheckConstraint(
            "jsonb_typeof(synonyms) = 'array'", name="clinical_definitions_synonyms_check"
        ),
        CheckConstraint("length(trim(notes)) > 0", name="clinical_definitions_notes_check"),
    )


class ClinicalDefinitionHistory(Base):
    """Every version a definition has ever had. Append-only.

    The definitions table holds what a term means *now*; this holds what it
    meant on every day it has existed. An audit row says it resolved
    `impaired renal function` at version 3, and this is where version 3 is.

    Deliberately not a foreign key to `clinical_definitions.id`: deleting a
    definition must not delete the record of what it used to say, for the same
    reason deleting a conversation does not delete its audit rows. A deleted
    term is a final history row with `action = 'deleted'`, and its earlier
    versions stay readable.

    One row per change rather than a diff: the row is the whole definition as
    it stood, so reading an old version is one SELECT and not a replay.
    """

    __tablename__ = "clinical_definition_history"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    definition_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    term: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    entity: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    logic: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    notes: Mapped[str] = mapped_column(Text, nullable=False)
    synonyms: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    invariants: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    status: Mapped[str] = mapped_column(Text, nullable=False)
    changed_by: Mapped[str] = mapped_column(Text, nullable=False)
    # Why the threshold moved. A `notes` field defends a threshold; this is
    # what defends a *change* to one, and it is required for the same reason.
    change_reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "action in ('created', 'updated', 'deleted')",
            name="clinical_definition_history_action_check",
        ),
        CheckConstraint(
            "length(trim(change_reason)) > 0", name="clinical_definition_history_reason_check"
        ),
        UniqueConstraint(
            "definition_id", "version", "action", name="clinical_definition_history_version_key"
        ),
        Index("clinical_definition_history_definition_idx", "definition_id", "version"),
    )


class QueryAudit(Base):
    """Every question asked, and what the system did with it. Append-only.

    Written on *every* attempt, including the ones that were refused. An audit
    log that only records successes cannot answer the question it exists for —
    "did anyone try to read that column" — which is the one a PHI audit asks.

    `conversation_id` is SET NULL on delete rather than CASCADE. Deleting a
    conversation must not delete the record that the question was asked; an
    audit trail a user can erase by tidying their chat list is not an audit
    trail.
    """

    __tablename__ = "query_audit"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
    )
    asked_by: Mapped[str] = mapped_column(Text, nullable=False)
    raw_question: Mapped[str] = mapped_column(Text, nullable=False)
    resolved_terms: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # Null when nothing was assembled — a refusal before generation, or a
    # clarifying question asked instead.
    executed_sql: Mapped[str | None] = mapped_column(Text, nullable=True)
    columns_touched: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    # The structured reason a query was refused. Paired with outcome by a CHECK:
    # a rejection with no reason is the log entry that is useless six months on.
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Which surface asked. The model's tool is one of several routes to the
    # same query layer now — a cohort view, an export, a curator's dry run —
    # and "did anyone export that cohort" is a different audit question from
    # "did the model ask for it".
    via: Mapped[str] = mapped_column(Text, nullable=False, default="tool", server_default="tool")
    # term -> version, for every definition this question resolved through.
    # This is what makes an old answer reproducible: the threshold it used is
    # in `clinical_definition_history`, keyed by exactly this.
    definition_versions: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    measures: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    group_by: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "outcome in ('answered', 'clarification_requested', 'rejected', 'error')",
            name="query_audit_outcome_check",
        ),
        CheckConstraint(
            "via in ('tool', 'cohort', 'explain', 'export', 'preview', 'browse')",
            name="query_audit_via_check",
        ),
        CheckConstraint(
            "(outcome in ('rejected', 'error')) = (rejection_reason is not null)",
            name="query_audit_reason_requires_rejection_check",
        ),
        CheckConstraint("row_count is null or row_count >= 0", name="query_audit_row_count_check"),
        Index("query_audit_created_idx", desc("created_at")),
        Index("query_audit_asked_by_idx", "asked_by", desc("created_at")),
    )


class SavedQuestion(Base):
    """A question worth asking again, kept as its resolved parts.

    Terms, measures and dimensions by name — never the SQL and never the rows.
    A saved question is re-run through the definitions layer every time it is
    opened, so it picks up an edited threshold rather than freezing one, and
    it is audited on each run like any other question. Saving the rows instead
    would be an answer cache, which this project refuses on purpose.
    """

    __tablename__ = "saved_questions"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    terms: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    measures: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    group_by: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("length(trim(name)) > 0", name="saved_questions_name_check"),
        CheckConstraint("jsonb_typeof(terms) = 'array'", name="saved_questions_terms_check"),
        Index("saved_questions_user_idx", "user_id", desc("created_at")),
    )


class UserRole(Base):
    """What a user may do beyond asking questions, and which rows they may see.

    Roles are rows keyed by user id rather than claims read off a token,
    because the worker has no token: it answers a clinical question on behalf
    of whoever owns the conversation, and needs the same answer the API would
    give. A row both processes can read is the only thing that gives it.

    `scope_states` is row-level access in its smallest honest form: a list of
    states a user's queries are confined to, applied in the WHERE clause by the
    assembler, and NULL meaning unconfined. It exists to prove the seam rather
    than to be a permission model — one hardcoded user has no need of one.
    """

    __tablename__ = "user_roles"

    user_id: Mapped[str] = mapped_column(Text, primary_key=True)
    roles: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    scope_states: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("jsonb_typeof(roles) = 'array'", name="user_roles_roles_check"),
    )


class UsageEvent(Base):
    """Metered use of the model, for the cost ceilings in `usage_service`.

    **Deliberately not derived from the transcript.** `event_records` already
    carries a message per send and the tokens per model call, but it cascades
    with its conversation — so a limit counted from it resets the moment a
    visitor deletes the conversation they spent it in, and a daily budget
    counted from it can be spent, erased and spent again. Like `query_audit`,
    this table has no foreign key to anything a user can delete.

    Two kinds, one row each: a `message` when a user sends one (amount 1), and
    `tokens` when the worker records a model call (amount = input + output).
    """

    __tablename__ = "usage_events"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("kind in ('message', 'tokens')", name="usage_events_kind_check"),
        CheckConstraint("amount >= 0", name="usage_events_amount_check"),
        # The two questions asked of this table: how much has everyone used
        # since midnight, and how many messages has this user sent this hour.
        Index("usage_events_kind_created_idx", "kind", "created_at"),
        Index("usage_events_user_kind_created_idx", "user_id", "kind", "created_at"),
    )
