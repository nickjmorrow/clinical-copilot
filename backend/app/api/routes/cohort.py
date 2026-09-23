"""Ad-hoc cohort and aggregate queries, their governed export, and the raw
table browser — SEMANTIC_LAYER.md §§ 3 and 18.

The same guarded path `find_patients` and a saved question's run both go
through (`clinical_query_service.answer_question`), reached directly rather
than through either of those.

**The drilldown** (`POST /clinical/query`) is the frontend's "view full
roster" affordance on a chat answer: it re-asks with the same terms the
model already resolved, but with every returnable column instead of the
three the model happened to ask for — a filtered raw view of an existing
answer, not a new query path, per SEMANTIC_LAYER.md's own framing of what a
drilldown is allowed to be.

**The export** (`POST /clinical/export`) is the same question, answered the
same guarded way, rendered as a CSV file instead of JSON rows — the moment
data leaves the system, per SEMANTIC_LAYER.md § 18, so it goes through the
same column allowlist and gets its own `query_audit` outcome (`via="export"`,
a value the schema named before anything used it)
rather than silently reusing the drilldown's.

**The browser** (`GET /clinical/patients`) is a different shape entirely — no
question, no resolved terms, just a page of the raw patient table for a
curator or auditor to look at directly. Gated `RequireReviewer`: this is not
something an ordinary chat session needs, and unlike the two routes above it
skips term resolution altogether — `clinical_query_service.browse_patients`
says why in its own docstring.

All three are still audited and still go through the same column allowlist
and row-level scope as everything else — none of them is a way around any of
it.
"""

import csv
import io
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response, status

from app.api.deps import CurrentUser, DbSession, RequireReviewer
from app.api.schemas import (
    ApiResponse,
    BrowsePageOut,
    CohortQueryIn,
    SavedQuestionRunOut,
    to_browse_page_out,
    to_saved_question_run_out,
)
from app.services import clinical_query_service
from app.services.clinical_query_service import ClinicalAnswer

router = APIRouter(prefix="/clinical", tags=["clinical"])


async def _answer(
    session: DbSession, user_id: str, body: CohortQueryIn, *, via: str
) -> ClinicalAnswer:
    asker = await clinical_query_service.build_asker(session, user_id=user_id)
    return await clinical_query_service.answer_question(
        session,
        asker,
        question=f"({via})",
        terms=body.terms,
        columns=body.columns or None,
        measures=body.measures,
        group_by=body.group_by,
        via=via,
    )


@router.post("/query")
async def run_cohort_query(
    body: CohortQueryIn, session: DbSession, user_id: CurrentUser
) -> ApiResponse[SavedQuestionRunOut]:
    answer = await _answer(session, user_id, body, via="cohort")
    return ApiResponse(data=to_saved_question_run_out(answer))


@router.post("/export")
async def export_cohort_query(
    body: CohortQueryIn, session: DbSession, user_id: CurrentUser
) -> Response:
    """The same question as `/query`, as a CSV file. A rejection or a
    clarification has no rows to hand back as a file, so both are a 422 here
    rather than a 200 carrying an empty download — the same distinction
    `/query`'s JSON `outcome` field draws, expressed the only way a binary
    file response can draw it."""
    answer = await _answer(session, user_id, body, via="export")
    if not answer.ok:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, answer.reason or "not answered")

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(answer.columns)
    writer.writerows([row.get(column) for column in answer.columns] for row in answer.rows)

    return Response(
        content=buffer.getvalue(),
        headers={"Content-Disposition": 'attachment; filename="cohort.csv"'},
        media_type="text/csv",
    )


@router.get("/patients")
async def browse_patients(
    session: DbSession,
    user_id: RequireReviewer,
    columns: Annotated[list[str] | None, Query()] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1)] = 50,
) -> ApiResponse[BrowsePageOut]:
    asker = await clinical_query_service.build_asker(session, user_id=user_id)
    result = await clinical_query_service.browse_patients(
        session, asker, columns=columns, offset=offset, limit=limit
    )
    return ApiResponse(data=to_browse_page_out(result))
