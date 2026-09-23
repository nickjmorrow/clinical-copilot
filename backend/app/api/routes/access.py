"""Row-level access, in its smallest honest form — SEMANTIC_LAYER.md § 19.

Self-service only: `PUT` changes the caller's own `scope_states`, never
someone else's — there is no user id in the body, so "edit someone else's
scope" is not even expressible here. With one hardcoded dev user this is a
way to prove the seam end to end (pick a state, watch every subsequent cohort
confine to it) rather than a permission model; see
`app/services/authz_service.py`'s own docstring on that distinction.

The write is gated `RequireCurator`, the same guard a definition edit gets:
changing what a user's own queries can see is exactly the kind of change
CONVENTIONS.md's authorization discipline exists to keep deliberate.
"""

from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession, RequireCurator
from app.api.schemas import AccessOut, AccessUpdateIn, ApiResponse
from app.services import authz_service, catalog_service

router = APIRouter(prefix="/access", tags=["access"])


async def _access_out(session: DbSession, *, user_id: str) -> AccessOut:
    roles = await authz_service.get_roles(session, user_id=user_id)
    scope_states = await authz_service.get_scope_states(session, user_id=user_id)
    available_states = await catalog_service.list_patient_states(session)
    return AccessOut(
        available_states=list(available_states),
        roles=sorted(roles),
        scope_states=scope_states,
        user_id=user_id,
    )


@router.get("/me")
async def get_my_access(session: DbSession, user_id: CurrentUser) -> ApiResponse[AccessOut]:
    return ApiResponse(data=await _access_out(session, user_id=user_id))


@router.put("/me")
async def update_my_access(
    body: AccessUpdateIn, session: DbSession, user_id: RequireCurator
) -> ApiResponse[AccessOut]:
    # Roles are untouched by this route (see AccessUpdateIn) — carry them
    # forward exactly as they are rather than requiring the caller to repeat
    # them back, which is how a client that forgot one silently drops a role.
    roles = await authz_service.get_roles(session, user_id=user_id)
    await authz_service.set_roles(
        session, user_id=user_id, roles=sorted(roles), scope_states=body.scope_states
    )
    return ApiResponse(data=await _access_out(session, user_id=user_id))
