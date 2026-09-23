"""The audit log's read side — `unresolved_term_report` and `summary` —
SEMANTIC_LAYER.md § 14.

`record_query` itself is exercised indirectly by every test in
`test_clinical_query.py` that checks `_audit_rows`; what has no coverage yet
is the grouping and ranking `unresolved_term_report` does over those rows,
which is the part worth pinning directly rather than only through a route.
"""

from app.services import audit_service
from app.services.audit_service import QueryAttempt


async def _clarification(session, *, question: str, asked_by: str = "dr-who") -> None:
    await audit_service.record_query(
        session,
        QueryAttempt(
            asked_by=asked_by,
            raw_question=question,
            outcome="clarification_requested",
        ),
    )


async def test_an_answered_question_never_appears_in_the_report(session):
    await audit_service.record_query(
        session,
        QueryAttempt(asked_by="dr-who", raw_question="how many elderly?", outcome="answered"),
    )

    report = await audit_service.unresolved_term_report(session)
    assert report == []


async def test_repeated_questions_are_grouped_and_counted(session):
    await _clarification(session, question="who has bad kidneys")
    await _clarification(session, question="who has bad kidneys")
    await _clarification(session, question="who is on a blood thinner")

    report = await audit_service.unresolved_term_report(session)
    by_question = {entry.raw_question: entry for entry in report}

    assert by_question["who has bad kidneys"].count == 2
    assert by_question["who is on a blood thinner"].count == 1


async def test_the_most_frequent_unresolved_question_sorts_first(session):
    await _clarification(session, question="rare phrasing")
    for _ in range(3):
        await _clarification(session, question="common phrasing")

    report = await audit_service.unresolved_term_report(session)
    assert report[0].raw_question == "common phrasing"
    assert report[0].count == 3


async def test_every_asker_is_recorded_once_each(session):
    await _clarification(session, question="who has bad kidneys", asked_by="dr-who")
    await _clarification(session, question="who has bad kidneys", asked_by="dr-house")
    await _clarification(session, question="who has bad kidneys", asked_by="dr-who")

    (entry,) = await audit_service.unresolved_term_report(session)
    assert entry.asked_by == ("dr-house", "dr-who")


async def test_the_limit_caps_how_many_questions_come_back(session):
    for i in range(5):
        await _clarification(session, question=f"question {i}")

    report = await audit_service.unresolved_term_report(session, limit=2)
    assert len(report) == 2
