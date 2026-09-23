"""The guarded path from a question to rows, and the audit trail behind it.

Every test here asserts two things: what the caller got back, and what landed
in `query_audit`. The second half is the point — a guardrail that refuses
correctly but leaves no record cannot answer the question a PHI audit asks.
"""

import json

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app import tools
from app.clinical import columns
from app.models import Conversation, QueryAudit
from app.services import (
    clinical_query_service,
    conversation_service,
    definition_service,
    seed_service,
    transcript_service,
)
from app.services.clinical_query_service import Asker
from app.tools.base import ToolContext
from tests.support.fixture import FIXTURE_SOURCE, FIXTURE_TODAY, RUNNING_EXAMPLE_NOT_SEVERE

ASKER = Asker(user_id="dr-who")


@pytest.fixture
async def seeded(session):
    # The clinical dataset is seeded once for the whole session — see
    # tests/integration/conftest.py. The two tests below that mutate it
    # (an inserted observation, a corrupted definition) restore what they
    # changed instead of relying on a per-test reset that no longer happens.
    return session


async def _audit_rows(session) -> list[QueryAudit]:
    result = await session.execute(select(QueryAudit).order_by(QueryAudit.created_at))
    return list(result.scalars().all())


async def _ask(session, *terms: str, columns=None, asker=ASKER):
    return await clinical_query_service.answer_question(
        session,
        asker,
        question="which patients should I worry about?",
        terms=list(terms),
        columns=columns,
        today=FIXTURE_TODAY,
    )


async def _ask_aggregate(session, *terms: str, measures, group_by, asker=ASKER):
    return await clinical_query_service.answer_question(
        session,
        asker,
        question="which patients should I worry about?",
        terms=list(terms),
        measures=measures,
        group_by=group_by,
        today=FIXTURE_TODAY,
    )


# --- the happy path ----------------------------------------------------------


async def test_a_resolved_question_returns_rows_and_its_definitions(seeded):
    answer = await _ask(seeded, "impaired renal function", "nephrotoxic medication")

    assert answer.ok
    assert answer.row_count == 8
    assert answer.columns == ("patient_id", "age", "sex")
    assert {r.term for r in answer.resolved} == {
        "impaired renal function",
        "nephrotoxic medication",
    }
    # The rationale travels with the answer — a count alone is not verifiable.
    assert all(r.notes.strip() for r in answer.resolved)


async def test_an_answer_cites_which_dataset_it_ran_against(seeded):
    """SEMANTIC_LAYER.md § 1's "answer" level of provenance: not just the SQL,
    but what it ran against. `clear_clinical_data` deletes every `DatasetMeta`
    row before a reload writes one, so there is exactly one to cite."""
    answer = await _ask(seeded, "impaired renal function")

    assert answer.dataset is not None
    assert "Synthea" in answer.dataset.source
    assert answer.dataset.as_of_date == FIXTURE_TODAY


async def test_an_answer_is_audited_with_the_sql_and_the_columns(seeded):
    await _ask(seeded, "impaired renal function", "nephrotoxic medication")

    (entry,) = await _audit_rows(seeded)
    assert entry.outcome == "answered"
    assert entry.asked_by == "dr-who"
    assert entry.row_count == 8
    assert entry.rejection_reason is None
    assert sorted(entry.resolved_terms) == [
        "impaired renal function",
        "nephrotoxic medication",
    ]
    # Literal-bound, so the entry says what actually ran.
    assert "60" in (entry.executed_sql or "")
    assert "observations.value_numeric" in entry.columns_touched
    assert "medication_annotations.value" in entry.columns_touched
    assert "prescriptions.end_date" in entry.columns_touched


async def test_the_default_answer_carries_no_direct_identifiers(seeded):
    answer = await _ask(seeded, "impaired renal function")
    assert "full_name" not in answer.columns
    assert "birth_date" not in answer.columns


# --- column access control ---------------------------------------------------


async def test_asking_for_a_name_is_refused(seeded):
    answer = await _ask(seeded, "impaired renal function", columns=["patient_id", "full_name"])

    assert answer.outcome == "rejected"
    assert "full_name" in (answer.reason or "")
    assert answer.rows == ()


async def test_a_refused_column_is_recorded_as_attempted(seeded):
    """'Did anyone try to read that column' is the question this table answers."""
    await _ask(seeded, "impaired renal function", columns=["birth_date"])

    (entry,) = await _audit_rows(seeded)
    assert entry.outcome == "rejected"
    assert entry.rejection_reason
    assert "birth_date" in entry.columns_touched
    assert entry.row_count is None


async def test_age_is_available_where_birth_date_is_not(seeded):
    """The whole argument for deriving age rather than storing it."""
    refused = await _ask(seeded, "elderly", columns=["birth_date"])
    assert refused.outcome == "rejected"

    allowed = await _ask(seeded, "elderly", columns=["patient_id", "age"])
    assert allowed.ok
    assert all(row["age"] >= 65 for row in allowed.rows)


async def test_an_invented_column_does_not_resolve(seeded):
    """Semantic binding: a hallucinated column is a refusal, not a database error."""
    answer = await _ask(seeded, "impaired renal function", columns=["diagnosis"])
    assert answer.outcome == "rejected"
    assert "diagnosis" in (answer.reason or "")


async def test_a_restricted_identifier_is_refused_even_though_it_is_a_real_column(seeded):
    """`ssn` is loaded and on the allowlist — it is denied, not unknown.

    The distinction matters for the message: a caller told "no such column"
    for `ssn` would reasonably infer it isn't in the dataset at all, when the
    truth is closer to home.
    """
    answer = await _ask(seeded, "impaired renal function", columns=["ssn"])
    assert answer.outcome == "rejected"
    assert "ssn" in (answer.reason or "")
    assert "identifiers" in (answer.reason or "")


async def test_a_role_granted_an_identifying_column_can_read_it(seeded, monkeypatch):
    """The per-role mechanism end to end, not just `resolve_columns` in
    isolation — SEMANTIC_LAYER.md § 19. Nobody is granted anything by default
    (see `columns.ROLE_IDENTIFYING_COLUMNS`'s own comment); this proves that
    if a role ever is, `Asker.roles` actually reaches the check the same way
    `scope_states` already does."""
    monkeypatch.setitem(columns.ROLE_IDENTIFYING_COLUMNS, "auditor", ("full_name",))
    auditor = Asker(user_id="dr-who", roles=frozenset({"auditor"}))

    denied = await _ask(seeded, "impaired renal function", columns=["full_name"])
    assert denied.outcome == "rejected"

    allowed = await _ask(
        seeded,
        "impaired renal function",
        columns=["patient_id", "full_name"],
        asker=auditor,
    )
    assert allowed.ok
    assert "full_name" in allowed.columns


# --- clarification -----------------------------------------------------------


async def test_an_unresolvable_term_asks_rather_than_guesses(seeded):
    answer = await _ask(seeded, "impaired renal function", "frailty")

    assert answer.outcome == "clarification_requested"
    assert answer.unresolved == ("frailty",)
    assert answer.rows == ()
    # The vocabulary goes back so the model can ask a useful question.
    assert any(entry["term"] == "impaired renal function" for entry in answer.vocabulary)


async def test_a_clarification_runs_no_query_but_is_still_audited(seeded):
    await _ask(seeded, "frailty")

    (entry,) = await _audit_rows(seeded)
    assert entry.outcome == "clarification_requested"
    assert entry.executed_sql is None
    assert entry.row_count is None


async def test_a_partial_resolution_never_narrows_the_question(seeded):
    """The dangerous case: answering one leg of a two-leg question.

    If this ever returns `answered`, the result is every patient with reduced
    kidney function — a much larger set than was asked about, presented as
    though it were the answer.
    """
    answer = await _ask(seeded, "impaired renal function", "wildly invented term")
    assert answer.outcome == "clarification_requested"
    assert answer.row_count == 0


# --- the row cap -------------------------------------------------------------


async def test_a_large_result_is_capped_and_says_so(seeded, monkeypatch):
    monkeypatch.setattr(clinical_query_service, "MAX_ROWS", 5)

    answer = await _ask(seeded, "elderly")

    assert answer.ok
    assert answer.row_count == 5
    assert answer.truncated


async def test_the_audit_records_the_returned_count_not_the_matching_count(seeded, monkeypatch):
    monkeypatch.setattr(clinical_query_service, "MAX_ROWS", 5)
    await _ask(seeded, "elderly")

    (entry,) = await _audit_rows(seeded)
    assert entry.row_count == 5


# --- the audit outlives the conversation -------------------------------------


async def test_deleting_a_conversation_does_not_delete_its_audit_trail(seeded):
    conversation = await conversation_service.create_conversation(seeded, user_id="dr-who")
    await clinical_query_service.answer_question(
        seeded,
        Asker(user_id="dr-who", conversation_id=conversation.id),
        question="who is at risk?",
        terms=["impaired renal function"],
        today=FIXTURE_TODAY,
    )

    # Read columns rather than ORM objects throughout. `ON DELETE SET NULL` is
    # applied by Postgres and never travels through the ORM, and
    # `expire_on_commit=False` means an object already in the identity map
    # would still be holding the old conversation id — the test would fail
    # against a database that had done exactly the right thing.
    async def audit_row() -> tuple:
        return (
            await seeded.execute(
                select(QueryAudit.id, QueryAudit.conversation_id, QueryAudit.raw_question)
            )
        ).one()

    before_id, before_conversation, _ = await audit_row()
    assert before_conversation == conversation.id

    await conversation_service.delete_conversation(seeded, conversation=conversation)

    after_id, after_conversation, question = await audit_row()
    assert after_id == before_id
    assert after_conversation is None
    assert question == "who is at risk?"

    gone = await seeded.execute(select(Conversation).where(Conversation.id == conversation.id))
    assert gone.scalar_one_or_none() is None


async def test_the_audit_table_rejects_a_rejection_with_no_reason(seeded):
    """The CHECK constraint, not the application, is what cannot be bypassed."""
    bad_insert = text("""
        insert into query_audit (asked_by, raw_question, outcome)
        values ('x', 'y', 'rejected')
    """)

    with pytest.raises(IntegrityError, match="query_audit_reason_requires_rejection_check"):
        await seeded.execute(bad_insert)

    await seeded.rollback()


# --- the tool boundary -------------------------------------------------------
#
# The service is tested above; these go through `tools.execute`, which is the
# surface the model actually touches — schema, handler, and the is_error flag
# that decides whether the model retries or asks.


def _context(session) -> ToolContext:
    return ToolContext(session=session, user_id="dr-who")


async def test_the_tool_answers_and_shows_its_working(seeded):
    output = await tools.execute(
        "find_patients",
        {
            "question": "who is on a nephrotoxic drug with bad kidneys?",
            "terms": ["impaired renal function", "nephrotoxic medication"],
            "measures": [],
            "group_by": [],
            "columns": [],
        },
        _context(seeded),
    )

    assert not output.is_error
    assert "8 matching patient(s)" in output.content
    # The definitions and the SQL travel with the answer, so a clinician can
    # check why these patients rather than taking the count on trust.
    assert "impaired renal function" in output.content
    assert "KDIGO" in output.content
    assert "SQL executed:" in output.content
    # SEMANTIC_LAYER.md § 1: the answer cites which dataset it ran against,
    # not just the SQL — the model can relay this if asked "where's this from".
    assert "Dataset: " in output.content
    assert "Synthea" in output.content
    # The structured half: the count the interface leads with, and no rows —
    # a patient list's rows are in the text, not duplicated into JSONB.
    assert output.data == {"aggregate": False, "rowCount": 8, "truncated": False}


async def test_a_clarification_carries_no_data(seeded):
    """No query ran, so there is nothing to count — which is exactly how the
    interface tells a clarification from an answer that matched nobody."""
    output = await tools.execute(
        "find_patients",
        {
            "question": "who is frail?",
            "terms": ["frailty"],
            "measures": [],
            "group_by": [],
            "columns": [],
        },
        _context(seeded),
    )

    assert not output.is_error
    assert output.data is None


async def test_an_aggregate_answer_survives_the_json_round_trip(seeded):
    """Regression test.

    `average eGFR`/`median creatinine` are Postgres NUMERIC and come back as
    `Decimal`, which has no JSON representation. `output.data` is written into
    the append-only `event_records.data` JSONB column by `add_tool_result` and
    sent to the browser as JSON for a chart to render from — either one raises
    on an un-converted `Decimal` buried in a row, which crashed every turn that
    asked for a numeric measure until `_json_safe` in `find_patients.py` fixed
    it.
    """
    output = await tools.execute(
        "find_patients",
        {
            "question": "average eGFR by age band",
            "terms": ["impaired renal function"],
            "measures": ["average eGFR"],
            "group_by": ["age band"],
            "columns": [],
        },
        _context(seeded),
    )

    assert not output.is_error
    assert output.data is not None
    json.dumps(output.data)  # must not raise

    for row in output.data["rows"]:
        assert isinstance(row["average eGFR"], float)

    conversation = await conversation_service.create_conversation(seeded, user_id="dr-who")
    await transcript_service.add_tool_result(
        seeded,
        conversation_id=conversation.id,
        tool_use_id="regression-check",
        content=output.content,
        is_error=output.is_error,
        data=output.data,
    )  # must not raise IntegrityError/TypeError from the JSONB write


async def test_age_bands_come_back_youngest_first(seeded):
    """Ordered by age, not by label. Sorting the labels as text put "under
    18" after "80+" — in the table, in the chart, and in every CSV — because
    "u" sorts after digits. The bands are an ordinal scale and the definition
    already lists them youngest first; the rows should agree with it."""
    answer = await _ask_aggregate(
        seeded, "living", measures=["patient count"], group_by=["age band"]
    )

    assert answer.ok
    labels = [row["age band"] for row in answer.rows]
    band_order = ["under 18", "18-44", "45-64", "65-79", "80+"]
    assert len(labels) >= 3, "the fixture should span several bands for this to mean anything"
    assert labels == sorted(labels, key=band_order.index)


async def test_a_question_about_drugs_rather_than_patients(seeded):
    """SEMANTIC_LAYER.md § 11's named example, through the tool boundary:
    'which nephrotoxins are most prescribed' groups by a medication-entity
    dimension, not a patient one — `terms` still narrows the population."""
    output = await tools.execute(
        "find_patients",
        {
            "question": "which nephrotoxins are most prescribed among the elderly?",
            "terms": ["elderly"],
            "measures": ["patient count"],
            "group_by": ["nephrotoxic medication name"],
            "columns": [],
        },
        _context(seeded),
    )

    assert not output.is_error
    assert output.data is not None
    assert output.data["columns"] == ["nephrotoxic medication name", "patient count"]
    assert output.data["rows"]
    counts = [row["patient count"] for row in output.data["rows"]]
    assert counts == sorted(counts, reverse=True), "most-prescribed should sort first"


async def test_mixing_patient_and_medication_dimensions_is_rejected(seeded):
    """One question, one entity — `sex` groups patients, `nephrotoxic
    medication name` groups drugs, and combining them would need two
    different FROM clauses in one result set."""
    answer = await _ask_aggregate(
        seeded,
        "elderly",
        measures=["patient count"],
        group_by=["sex", "nephrotoxic medication name"],
    )
    assert answer.outcome == "rejected"
    assert "more than one entity" in (answer.reason or "")


async def test_a_medication_dimension_refuses_an_averaged_measure(seeded):
    answer = await _ask_aggregate(
        seeded, "elderly", measures=["average eGFR"], group_by=["nephrotoxic medication name"]
    )
    assert answer.outcome == "rejected"
    assert "patient count" in (answer.reason or "")


async def test_the_tool_cannot_be_asked_for_a_name(seeded):
    output = await tools.execute(
        "find_patients",
        {
            "question": "give me their names",
            "terms": ["impaired renal function"],
            "measures": [],
            "group_by": [],
            "columns": ["full_name"],
        },
        _context(seeded),
    )

    assert output.is_error
    assert "full_name" in output.content


async def test_an_unresolved_term_is_not_an_error_the_model_should_retry(seeded):
    """is_error would tell the model to fix itself, which here means guess again.

    An unresolvable term is a question for the user, so it comes back as an
    ordinary result carrying the vocabulary and an instruction not to guess.
    """
    output = await tools.execute(
        "find_patients",
        {
            "question": "who is frail?",
            "terms": ["frailty"],
            "measures": [],
            "group_by": [],
            "columns": [],
        },
        _context(seeded),
    )

    assert not output.is_error
    assert "Do NOT guess" in output.content
    assert "impaired renal function" in output.content


async def test_the_tool_schema_offers_no_way_to_pass_sql(seeded):
    """The architectural claim, asserted against the schema the model is sent."""
    (definition,) = [d for d in tools.definitions() if d.name == "find_patients"]
    properties = definition.input_schema["properties"]

    assert set(properties) == {"question", "terms", "measures", "group_by", "columns"}
    assert properties["columns"]["items"]["enum"] == [
        "patient_id",
        "age",
        "sex",
        "race",
        "state",
    ]


async def test_a_missing_argument_is_a_result_not_a_dead_turn(seeded):
    output = await tools.execute("find_patients", {}, _context(seeded))
    assert output.is_error


# --- the self-correction loop ------------------------------------------------
#
# A refusal comes back as `is_error=True`, the adapter feeds it to the model as
# an ordinary tool result, and the model corrects itself. That much is the
# template's machinery. What is asserted here is the cap on it, and the one
# thing the cap must not count.


def _call(**overrides) -> dict:
    base = {"question": "who?", "terms": ["elderly"], "measures": [], "group_by": [], "columns": []}
    base.update(overrides)
    return base


async def test_a_refusal_lets_the_model_correct_itself(seeded):
    """The retry that is usually right: asked for a name, asks again for age."""
    context = _context(seeded)

    first = await tools.execute("find_patients", _call(columns=["full_name"]), context)
    assert first.is_error
    assert context.attempts.failures_for("find_patients") == 1

    second = await tools.execute("find_patients", _call(columns=["age"]), context)
    assert not second.is_error
    assert "matching patient(s)" in second.content


async def test_the_third_failure_is_refused_with_an_explanation(seeded):
    context = _context(seeded)
    bad = _call(columns=["full_name"])

    assert (await tools.execute("find_patients", bad, context)).is_error
    assert (await tools.execute("find_patients", bad, context)).is_error

    third = await tools.execute("find_patients", bad, context)
    # Not an error: an error is an instruction to fix and retry, which is the
    # loop this exists to end.
    assert not third.is_error
    assert "will not be run again" in third.content
    assert "Tell the user" in third.content


async def test_the_refused_attempt_never_reaches_the_database(seeded):
    """Giving up must not also be a query. Three attempts, two audit rows."""
    context = _context(seeded)
    bad = _call(columns=["birth_date"])

    for _ in range(3):
        await tools.execute("find_patients", bad, context)

    entries = await _audit_rows(seeded)
    assert len(entries) == 2
    assert {entry.outcome for entry in entries} == {"rejected"}


async def test_a_clarification_does_not_consume_a_retry(seeded):
    """Asking the user, getting an answer, asking again is the loop working.

    If a clarification counted as a failure, two rounds of "which term did you
    mean?" would exhaust the budget and the third — the one with the user's
    actual answer in it — would be refused.
    """
    context = _context(seeded)

    for _ in range(3):
        output = await tools.execute("find_patients", _call(terms=["frailty"]), context)
        assert not output.is_error
        assert "Do NOT guess" in output.content

    assert context.attempts.failures_for("find_patients") == 0

    # And the real question still runs afterwards.
    answer = await tools.execute("find_patients", _call(terms=["elderly"]), context)
    assert not answer.is_error
    assert "matching patient(s)" in answer.content


async def test_each_turn_starts_with_a_fresh_budget(seeded):
    """The ledger's lifetime is the turn. A new context is a new turn."""
    bad = _call(columns=["full_name"])

    first_turn = _context(seeded)
    await tools.execute("find_patients", bad, first_turn)
    await tools.execute("find_patients", bad, first_turn)
    assert not (await tools.execute("find_patients", bad, first_turn)).is_error

    second_turn = _context(seeded)
    assert (await tools.execute("find_patients", bad, second_turn)).is_error


# --- the vocabulary in the prompt --------------------------------------------
#
# Found by the first real conversation, which no test had caught: asked to
# narrow a result to "over 65", the model filtered the rows it already had
# rather than re-querying with the `elderly` term — because it had never been
# told `elderly` exists. It was transparent about having invented a `> 65`
# boundary, but the hospital defines that term as `>= 65`, and a follow-up
# answered from memory is neither audited nor reproducible.


async def test_the_prompt_lists_every_defined_term(seeded):
    prompt = await definition_service.with_vocabulary(seeded, base="BASE")

    assert prompt.startswith("BASE")
    for definition in await definition_service.list_definitions(seeded):
        assert definition.term in prompt


async def test_the_prompt_carries_synonyms_so_a_paraphrase_still_lands(seeded):
    prompt = await definition_service.with_vocabulary(seeded, base="BASE")
    assert "ckd" in prompt


async def test_the_prompt_never_leaks_a_threshold(seeded):
    """The model picks the term; it must not be reasoning about the number.

    Showing it `eGFR < 60` invites exactly the behaviour the definitions layer
    exists to prevent — the model deciding a threshold is close enough and
    applying it itself.
    """
    prompt = await definition_service.with_vocabulary(seeded, base="BASE")

    assert "lab_threshold" not in prompt
    assert "observation_threshold" not in prompt
    assert "most_recent" not in prompt
    assert "nephrotoxic_risk" not in prompt


async def test_an_empty_definitions_table_leaves_the_prompt_alone(session):
    """No definitions is not an excuse to append an empty heading.

    `clinical_definitions` is part of the clinical dataset seeded once for
    the whole session (see tests/integration/conftest.py), so "empty" has to
    be arranged here rather than inherited from a per-test TRUNCATE — and
    restored afterward, the same as the other tests in this file that touch
    shared clinical state.
    """
    await session.execute(text("truncate clinical_definitions, clinical_definition_history"))
    await session.commit()
    definition_service.invalidate()
    try:
        assert await definition_service.with_vocabulary(session, base="BASE") == "BASE"
    finally:
        # Private, deliberately — this is the same helper `seed_all` uses,
        # reached into directly because a test restoring shared state is
        # exactly the case CONVENTIONS.md's SLF001 exemption for tests/ is for.
        await seed_service._insert_definitions(session)
        await session.commit()
        definition_service.invalidate()


# --- caching -----------------------------------------------------------------
#
# The definitions are cached; answers are not. Caching an answer means serving
# yesterday's renal function to today's question, and the patient whose eGFR
# just fell is precisely the one the query exists to surface.


async def test_the_same_question_twice_is_not_served_from_a_cache(seeded):
    """The answer must come from the database every time.

    A patient crossing the eGFR threshold between two identical questions must
    change the second answer. No TTL makes a stale clinical answer acceptable;
    it only decides how long the system is allowed to be confidently wrong.
    """
    before = await _ask(seeded, "severely impaired renal function")

    # RUNNING_EXAMPLE_NOT_SEVERE is impaired (42.3) but not severe (>=30) in
    # the fixture — see tests/support/fixture.py. A new, later eGFR reading
    # below 30 should move them into the severe cohort on the very next ask.
    #
    # `observations` is part of the clinical dataset seeded once for the
    # whole session (see tests/integration/conftest.py) rather than truncated
    # per test, so this real, committed insert — the whole point of the test
    # is that it is real and committed — has to be undone explicitly rather
    # than left for a per-test reset that no longer happens.
    inserted_id = await seeded.scalar(
        text("""
            insert into observations
                (patient_id, code, system, display, unit, value_numeric, taken_at)
            select id, '33914-3', 'http://loinc.org',
                   'Glomerular filtration rate', 'mL/min/{1.73_m2}', 12.0, now()
            from patients where source_id = :source_id
            returning id
        """),
        {"source_id": RUNNING_EXAMPLE_NOT_SEVERE},
    )
    await seeded.commit()
    try:
        after = await _ask(seeded, "severely impaired renal function")

        assert after.row_count == before.row_count + 1
        assert RUNNING_EXAMPLE_NOT_SEVERE in {row["patient_id"] for row in after.rows}
    finally:
        await seeded.execute(text("delete from observations where id = :id"), {"id": inserted_id})
        await seeded.commit()


async def test_the_vocabulary_is_cached_between_questions(seeded):
    """Two questions, one read of the definitions table."""
    definition_service.invalidate()

    first = await definition_service.load_vocabulary(seeded)
    second = await definition_service.load_vocabulary(seeded)

    # Same object, not merely an equal one — it was not rebuilt.
    assert first is second


async def test_invalidating_forces_a_rebuild(seeded):
    first = await definition_service.load_vocabulary(seeded)
    definition_service.invalidate()
    second = await definition_service.load_vocabulary(seeded)

    assert first is not second
    assert {d.term for d in first.definitions} == {d.term for d in second.definitions}


async def test_reseeding_invalidates_the_cache(seeded):
    """The one thing in this codebase that rewrites the definitions table.

    Without this the cache serves terms whose rows no longer exist, which is
    the single way a TTL cache of reference data actually goes wrong.
    """
    cached = await definition_service.load_vocabulary(seeded)
    await seed_service.seed_all(seeded, source=FIXTURE_SOURCE, reset=True)
    rebuilt = await definition_service.load_vocabulary(seeded)

    assert cached is not rebuilt


async def test_an_unusable_definition_is_reported_not_skipped(seeded):
    """A row the assembler cannot build must refuse, never narrow the question.

    `clinical_definitions` is part of the clinical dataset seeded once for
    the whole session (see tests/integration/conftest.py), so corrupting
    `elderly` here has to be undone afterward — every other test in this
    suite that resolves `elderly` is trusting this row to mean what
    `reference_data.py` says it means.
    """
    original_logic = await seeded.scalar(
        text("select logic from clinical_definitions where term = 'elderly'")
    )
    try:
        await seeded.execute(
            text("""
                update clinical_definitions
                set logic = '{"type": "observation_threshold", "codes": ["unicorn-count"]}'::jsonb
                where term = 'elderly'
            """)
        )
        await seeded.commit()
        definition_service.invalidate()

        resolution = await definition_service.resolve_terms(seeded, terms=["elderly"])

        assert not resolution.is_complete
        assert resolution.resolved == ()
        assert resolution.invalid
        assert resolution.invalid[0][0] == "elderly"
        assert resolution.invalid[0][1]
    finally:
        await seeded.execute(
            text(
                "update clinical_definitions set logic = cast(:logic as jsonb) "
                "where term = 'elderly'"
            ),
            {"logic": json.dumps(original_logic)},
        )
        await seeded.commit()
        definition_service.invalidate()
