"""Invariants: a filter's claimed relationship to another filter, checked
against the loaded dataset — SEMANTIC_LAYER.md § 13.

Not enforced at save time (the data can shift under a threshold that was true
when it was written); checked live by `definition_service.check_model()`, the
same way a filter matching nobody already is. `reference_data.py` declares one
real one — `severely impaired renal function` is a subset of `impaired renal
function`, true by construction (eGFR < 30 implies eGFR < 60) — which is what
the first test below actually exercises, against the real seeded dataset
rather than a synthetic fixture built for the test.

Every test that mutates `clinical_definitions` restores it — see
`tests/integration/conftest.py`'s module docstring: the clinical dataset is
shared for the whole test session, not truncated per test.
"""

import pytest
from sqlalchemy import text

from app.services import definition_service


@pytest.fixture
async def seeded(session):
    return session


def _find(warnings, term: str):
    return [w for w in warnings if w.term == term]


async def test_the_real_seeded_invariant_holds(seeded):
    """`severely impaired renal function` is declared `subset_of` `impaired
    renal function` in reference_data.py. Against the real dataset, it must
    produce no warning — this is the true, unmodified case."""
    warnings = await definition_service.check_model(seeded)
    assert _find(warnings, "severely impaired renal function") == []


async def test_a_broken_subset_is_reported_with_a_count(seeded):
    """Break the relationship on purpose — widen the severe threshold past
    the impaired one — and restore it afterward, per this file's module
    docstring."""
    try:
        await seeded.execute(
            text("""
                update clinical_definitions
                set logic = jsonb_set(logic, '{value}', '200')
                where term = 'severely impaired renal function'
            """)
        )
        await seeded.commit()
        definition_service.invalidate()

        warnings = await definition_service.check_model(seeded)
        (warning,) = _find(warnings, "severely impaired renal function")
        assert "subset of 'impaired renal function'" in warning.message
        assert "matching patient(s) are not in it" in warning.message
    finally:
        await seeded.execute(
            text("""
                update clinical_definitions
                set logic = jsonb_set(logic, '{value}', '30')
                where term = 'severely impaired renal function'
            """)
        )
        await seeded.commit()
        definition_service.invalidate()


async def test_a_real_subset_relationship_created_through_the_service(seeded):
    """Not just the one seeded example — the mechanism itself, exercised
    through `create_definition` the way a curator would use it, with two
    throwaway terms that do not exist anywhere else."""
    broad = await definition_service.create_definition(
        seeded,
        term="test-only: living",
        kind="filter",
        entity="patient",
        description="Not recorded as deceased.",
        logic={"type": "vital_status", "status": "alive"},
        notes="Test fixture for the invariant mechanism.",
        changed_by="test",
        change_reason="test",
    )
    narrow = await definition_service.create_definition(
        seeded,
        term="test-only: living and elderly",
        kind="filter",
        entity="patient",
        description="Alive and 65 or older.",
        logic={
            "type": "all_of",
            "of": [
                {"type": "term", "term": "test-only: living"},
                {"type": "age_threshold", "operator": ">=", "value": 65},
            ],
        },
        notes="Test fixture for the invariant mechanism.",
        invariants=[{"type": "subset_of", "term": "test-only: living"}],
        changed_by="test",
        change_reason="test",
    )
    try:
        warnings = await definition_service.check_model(seeded)
        assert _find(warnings, "test-only: living and elderly") == []
    finally:
        # `narrow` before `broad`: `broad`'s row has no FK from `narrow`, but
        # deleting in creation order is one less thing to think about if that
        # ever changes.
        await definition_service.delete_definition(
            seeded, definition=narrow, changed_by="test", change_reason="test cleanup"
        )
        await definition_service.delete_definition(
            seeded, definition=broad, changed_by="test", change_reason="test cleanup"
        )


async def test_disjoint_from_reports_the_overlap(seeded):
    """`elderly` and `impaired renal function` are not disjoint in the real
    dataset — this is the deliberately-wrong claim, and the count in the
    message should be real, not zero."""
    claim = await definition_service.create_definition(
        seeded,
        term="test-only: falsely disjoint",
        kind="filter",
        entity="patient",
        description="Elderly patients, wrongly claimed disjoint from impaired renal function.",
        logic={"type": "term", "term": "elderly"},
        notes="Test fixture for the invariant mechanism.",
        invariants=[{"type": "disjoint_from", "term": "impaired renal function"}],
        changed_by="test",
        change_reason="test",
    )
    try:
        warnings = await definition_service.check_model(seeded)
        (warning,) = _find(warnings, "test-only: falsely disjoint")
        assert "disjoint from 'impaired renal function'" in warning.message
        assert "patient(s) match both" in warning.message
    finally:
        await definition_service.delete_definition(
            seeded,
            definition=claim,
            changed_by="test",
            change_reason="test cleanup",
        )


async def test_an_invariant_referencing_an_unknown_term_is_reported(seeded):
    claim = await definition_service.create_definition(
        seeded,
        term="test-only: dangling invariant",
        kind="filter",
        entity="patient",
        description="Any patient.",
        logic={"type": "vital_status", "status": "alive"},
        notes="Test fixture for the invariant mechanism.",
        invariants=[{"type": "subset_of", "term": "not a real term"}],
        changed_by="test",
        change_reason="test",
    )
    try:
        warnings = await definition_service.check_model(seeded)
        (warning,) = _find(warnings, "test-only: dangling invariant")
        assert "not a defined term" in warning.message
    finally:
        await definition_service.delete_definition(
            seeded,
            definition=claim,
            changed_by="test",
            change_reason="test cleanup",
        )


async def test_an_invariant_referencing_a_measure_is_reported(seeded):
    """`patient count` is real and published, but it is a measure, not a
    filter — an invariant naming it cannot be evaluated as a cohort."""
    claim = await definition_service.create_definition(
        seeded,
        term="test-only: references a measure",
        kind="filter",
        entity="patient",
        description="Any patient.",
        logic={"type": "vital_status", "status": "alive"},
        notes="Test fixture for the invariant mechanism.",
        invariants=[{"type": "subset_of", "term": "patient count"}],
        changed_by="test",
        change_reason="test",
    )
    try:
        warnings = await definition_service.check_model(seeded)
        (warning,) = _find(warnings, "test-only: references a measure")
        assert "not a usable filter" in warning.message
    finally:
        await definition_service.delete_definition(
            seeded,
            definition=claim,
            changed_by="test",
            change_reason="test cleanup",
        )
