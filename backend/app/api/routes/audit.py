"""The audit log, read back — SEMANTIC_LAYER.md § 14.

`query_audit` is written on every attempt, from every surface, whether it
answered or not — see `app/services/audit_service.py`. The one view exposed
here is the backlog: every question the system had to ask a clarification
for, grouped by the raw question and ranked by how often it has come up. It
is a read-only page over rows that already exist, not a new capability, which
is the whole reason this file is short.

Gated `RequireReviewer` (curator or auditor): this is a curator deciding what
to define next, or an auditor reviewing what the system could not answer.
Unlike the definitions, which anyone may read, it stays closed — its rows are
other people's questions, verbatim, and on the public demo that would be every
visitor reading every other visitor's.
"""

from fastapi import APIRouter

from app.api.deps import DbSession, RequireReviewer
from app.api.schemas import ApiResponse, UnresolvedTermOut, to_unresolved_term_out
from app.services import audit_service

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/unresolved-terms")
async def get_unresolved_terms(
    session: DbSession, _user_id: RequireReviewer
) -> ApiResponse[list[UnresolvedTermOut]]:
    entries = await audit_service.unresolved_term_report(session)
    return ApiResponse(data=[to_unresolved_term_out(entry) for entry in entries])
