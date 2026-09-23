"""The golden dataset, run against the deterministic half of the system.

Every case in `tests/support/eval_cases.py` that is not `live_only` is walked
here: its terms go straight into `clinical_query_service`, and the outcome, the
row count and the named anchors are checked. No model is involved, nothing
reaches the network, and it runs on every commit.

What this suite can prove is "given the right terms, the answer is right".
What it cannot prove is that a model picks the right terms — that is
`tests/live/`, which costs money and is deliberately not in `scripts/check.sh`.
Keeping the two apart means a red build has exactly one meaning.

A failure here prints the case's `pins` field, because "expected 8, got 7" is
not a debuggable message and "the contextual tier stopped being excluded" is.
"""

import pytest

from app.services import clinical_query_service
from app.services.clinical_query_service import Asker
from tests.support.eval_cases import HERMETIC_CASES, EvalCase
from tests.support.fixture import FIXTURE_TODAY

ASKER = Asker(user_id="eval")


@pytest.fixture
async def seeded(session):
    """The cohort. Every case here is read-only, and the clinical dataset is
    seeded once for the whole session — see tests/integration/conftest.py —
    so there is nothing left to do here but hand back the session."""
    return session


def _describe(case: EvalCase) -> str:
    lines = [f"case {case.id!r} failed.", f"  question: {case.question}", f"  pins: {case.pins}"]
    if case.found_by:
        lines.append(f"  in the set because: {case.found_by}")
    return "\n".join(lines)


@pytest.mark.parametrize("case", HERMETIC_CASES, ids=lambda c: c.id)
async def test_golden_case(case: EvalCase, seeded):
    answer = await clinical_query_service.answer_question(
        seeded,
        ASKER,
        question=case.question,
        terms=list(case.terms),
        columns=list(case.columns) if case.columns else None,
        today=FIXTURE_TODAY,
    )

    context = _describe(case)

    assert answer.outcome == case.outcome, (
        f"{context}\n  expected outcome {case.outcome!r}, got {answer.outcome!r}"
        f"\n  reason: {answer.reason}"
    )

    if case.row_count is not None:
        assert answer.row_count == case.row_count, (
            f"{context}\n  expected {case.row_count} row(s), got {answer.row_count}"
        )

    returned = {row.get("patient_id") for row in answer.rows}

    missing = sorted(set(case.must_include) - returned)
    assert not missing, f"{context}\n  these patients should have matched and did not: {missing}"

    present = sorted(set(case.must_exclude) & returned)
    assert not present, f"{context}\n  these patients matched and should not have: {present}"

    for fragment in case.must_say:
        haystack = f"{answer.reason or ''} {' '.join(answer.unresolved)}"
        assert fragment in haystack, (
            f"{context}\n  expected the reply to mention {fragment!r}; it said: {answer.reason!r}"
        )


async def test_the_dataset_covers_every_outcome():
    """A set that only contains happy paths is a set that proves very little."""
    covered = {case.outcome for case in HERMETIC_CASES}
    assert covered == {"answered", "clarification_requested", "rejected"}


async def test_the_dataset_is_a_legitimate_size():
    """15-25 was the target. Coverage of failure modes matters more than volume."""
    assert 15 <= len(HERMETIC_CASES) <= 25


async def test_every_case_says_what_it_pins():
    """A case nobody can explain is a case nobody will dare delete when it breaks."""
    for case in HERMETIC_CASES:
        assert case.pins.strip(), case.id
