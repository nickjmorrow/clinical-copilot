"""What this app can be asked, and what it holds.

Read-only and unauthenticated in the same sense as the rest of the app: it
exposes the vocabulary and aggregate counts, never a patient row. A reader
deciding what to type does not need a session and should not need to spend a
model call to find out what the system understands.
"""

from fastapi import APIRouter

from app.api.deps import DbSession
from app.api.schemas import ApiResponse, ClinicalContextOut, to_clinical_context
from app.services import catalog_service, definition_service

router = APIRouter(tags=["clinical"])


@router.get("/clinical/context")
async def clinical_context(session: DbSession) -> ApiResponse[ClinicalContextOut]:
    """The defined terms and the shape of the dataset behind them.

    Served from the same rows the query layer resolves against, so the panel a
    reader sees and the vocabulary the model is given cannot disagree. A
    hard-coded list in the client would be a second copy, wrong the first time
    a definition changed.
    """
    definitions = await definition_service.list_definitions(session)
    catalog = await catalog_service.load_catalog(session)
    return ApiResponse(data=to_clinical_context(definitions, catalog))
