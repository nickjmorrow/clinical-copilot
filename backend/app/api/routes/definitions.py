"""The authoring surface: reading and writing the definitions layer itself.

Separate from `clinical.py`'s `/clinical/context`, which is the model- and
reader-facing view and deliberately withholds `logic` — see that module's
docstring and SEMANTIC_LAYER.md § 2. Everything here shows `logic`, because
the audience is a curator reviewing or changing what a term means, and an
auditor reviewing what is live; `api/deps.RequireReviewer` gates reads to
those two roles, `RequireCurator` gates every write to one.

Route order matters: `/definitions/export` and `/definitions/preview` are
declared before `/definitions/{definition_id}`, or FastAPI would try to parse
`"export"` and `"preview"` as a UUID path parameter.
"""

import uuid

from fastapi import APIRouter, HTTPException, status

from app.api.deps import DbSession, RequireCurator, RequireReviewer
from app.api.schemas import (
    ApiResponse,
    ChangeReasonIn,
    DefinitionCreateIn,
    DefinitionHistoryOut,
    DefinitionOut,
    DefinitionPreviewIn,
    DefinitionPreviewOut,
    DefinitionUpdateIn,
    ModelWarningOut,
    to_definition_history_out,
    to_definition_out,
    to_model_warning_out,
)
from app.clinical.predicates import (
    InvalidPredicateError,
    parse_dimension,
    parse_measure,
    parse_predicate,
)
from app.logging import get_logger
from app.models import ClinicalDefinition
from app.services import clinical_query_service, definition_service
from app.services.clinical_query_service import Asker

logger = get_logger(__name__)
router = APIRouter(prefix="/clinical", tags=["clinical"])


async def _get_or_404(session: DbSession, definition_id: uuid.UUID) -> ClinicalDefinition:
    definition = await definition_service.get_definition(session, definition_id=definition_id)
    if definition is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No definition with that id.")
    return definition


@router.get("/definitions")
async def list_definitions(
    session: DbSession, _user_id: RequireReviewer
) -> ApiResponse[list[DefinitionOut]]:
    rows = await definition_service.list_definitions(session, include_unpublished=True)
    return ApiResponse(data=[to_definition_out(row) for row in rows])


@router.get("/definitions/export")
async def export_definitions(
    session: DbSession, _user_id: RequireReviewer
) -> ApiResponse[list[DefinitionOut]]:
    """The whole model as JSON — every status, in one response.

    The backup and diff story this project gets for choosing database rows
    over git-tracked files: not version control, but a snapshot a curator can
    pull down before a risky edit, or archive on a schedule outside this app.
    Definitions live in the database rather than in git-tracked files so a
    curator can edit, version and publish one without a code deploy.
    """
    rows = await definition_service.list_definitions(session, include_unpublished=True)
    return ApiResponse(data=[to_definition_out(row) for row in rows])


@router.post("/definitions/preview")
async def preview_definition(
    body: DefinitionPreviewIn, session: DbSession, user_id: RequireCurator
) -> ApiResponse[DefinitionPreviewOut]:
    """How many patients a *proposed* `logic` would match, without saving it.

    Only a filter has a cohort to preview. A measure or a dimension still
    goes through its own parser here, so a curator gets the same shape
    feedback before saving that `create`/`update` would give after —
    SEMANTIC_LAYER.md § 6's "an editor can tell you before you save."
    """
    if body.kind == "measure":
        try:
            parse_measure(body.logic)
        except InvalidPredicateError as invalid:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(invalid)) from invalid
        return ApiResponse(data=DefinitionPreviewOut(patient_count=None))

    if body.kind == "dimension":
        try:
            parse_dimension(body.logic)
        except InvalidPredicateError as invalid:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(invalid)) from invalid
        return ApiResponse(data=DefinitionPreviewOut(patient_count=None))

    try:
        predicate = parse_predicate(body.logic)
        # A proposal can be `{"type": "all_of", "of": [{"type": "term", ...}, ...]}`
        # — composed from terms that already exist, like the running example
        # itself. The assembler only ever sees predicates `load_vocabulary`
        # has already substituted, so this preview needs the same
        # substitution before it reaches `preview_definition`.
        predicate = await definition_service.resolve_references(session, predicate)
    except InvalidPredicateError as invalid:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(invalid)) from invalid

    asker = Asker(user_id=user_id)
    count = await clinical_query_service.preview_definition(session, asker, predicate=predicate)
    return ApiResponse(data=DefinitionPreviewOut(patient_count=count))


@router.post("/definitions", status_code=status.HTTP_201_CREATED)
async def create_definition(
    body: DefinitionCreateIn, session: DbSession, user_id: RequireCurator
) -> ApiResponse[DefinitionOut]:
    try:
        row = await definition_service.create_definition(
            session,
            term=body.term,
            kind=body.kind,
            entity=body.entity,
            description=body.description,
            logic=body.logic,
            notes=body.notes,
            synonyms=body.synonyms,
            invariants=body.invariants,
            status=body.status,
            owner=body.owner,
            changed_by=user_id,
            change_reason=body.change_reason,
        )
    except InvalidPredicateError as invalid:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(invalid)) from invalid
    except definition_service.DefinitionConflictError as conflict:
        raise HTTPException(status.HTTP_409_CONFLICT, str(conflict)) from conflict
    return ApiResponse(data=to_definition_out(row))


@router.get("/definitions/{definition_id}")
async def get_definition(
    definition_id: uuid.UUID, session: DbSession, _user_id: RequireReviewer
) -> ApiResponse[DefinitionOut]:
    row = await _get_or_404(session, definition_id)
    return ApiResponse(data=to_definition_out(row))


@router.get("/definitions/{definition_id}/history")
async def get_definition_history(
    definition_id: uuid.UUID, session: DbSession, _user_id: RequireReviewer
) -> ApiResponse[list[DefinitionHistoryOut]]:
    await _get_or_404(session, definition_id)
    rows = await definition_service.definition_history(session, definition_id=definition_id)
    return ApiResponse(data=[to_definition_history_out(row) for row in rows])


@router.patch("/definitions/{definition_id}")
async def update_definition(
    definition_id: uuid.UUID, body: DefinitionUpdateIn, session: DbSession, user_id: RequireCurator
) -> ApiResponse[DefinitionOut]:
    row = await _get_or_404(session, definition_id)
    try:
        updated = await definition_service.update_definition(
            session,
            definition=row,
            kind=body.kind,
            entity=body.entity,
            description=body.description,
            logic=body.logic,
            notes=body.notes,
            synonyms=body.synonyms,
            invariants=body.invariants,
            status=body.status,
            owner=body.owner,
            changed_by=user_id,
            change_reason=body.change_reason,
        )
    except InvalidPredicateError as invalid:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(invalid)) from invalid
    except definition_service.DefinitionConflictError as conflict:
        raise HTTPException(status.HTTP_409_CONFLICT, str(conflict)) from conflict
    return ApiResponse(data=to_definition_out(updated))


@router.post("/definitions/{definition_id}/publish")
async def publish_definition(
    definition_id: uuid.UUID, body: ChangeReasonIn, session: DbSession, user_id: RequireCurator
) -> ApiResponse[DefinitionOut]:
    """The explicit approval step. `PATCH` can set `status` to anything,
    including `published`, but this is the route worth having separately: one
    action whose whole job is "this is reviewed and live now," with its own
    audited reason, rather than status happening to be one of several fields
    that changed in an edit."""
    row = await _get_or_404(session, definition_id)
    updated = await definition_service.update_definition(
        session,
        definition=row,
        status="published",
        changed_by=user_id,
        change_reason=body.change_reason,
    )
    return ApiResponse(data=to_definition_out(updated))


@router.delete("/definitions/{definition_id}")
async def delete_definition(
    definition_id: uuid.UUID, body: ChangeReasonIn, session: DbSession, user_id: RequireCurator
) -> ApiResponse[None]:
    row = await _get_or_404(session, definition_id)
    await definition_service.delete_definition(
        session, definition=row, changed_by=user_id, change_reason=body.change_reason
    )
    return ApiResponse(data=None)


@router.get("/model/check")
async def check_model(
    session: DbSession, _user_id: RequireReviewer
) -> ApiResponse[list[ModelWarningOut]]:
    warnings = await definition_service.check_model(session)
    return ApiResponse(data=[to_model_warning_out(w) for w in warnings])
