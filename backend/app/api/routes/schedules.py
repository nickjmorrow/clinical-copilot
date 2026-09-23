"""Scheduled agent runs.

A schedule is a prompt plus a cadence. The worker expands due rows into
agent_run tasks; nothing here knows how they execute, which is why adding a
schedule cannot slow down or break the thing that runs them.

There is no UI for this yet — deliberately. The machinery is what was missing;
a form is an afternoon whenever you want one.

**Curators only.** A schedule is the model running on its own, on a timer, on
the deployment's API key — the one request here that keeps costing money after
whoever made it has gone. Gated with the same role as editing a definition;
in a public deployment no visitor holds it.
"""

import uuid

from fastapi import APIRouter, HTTPException, status

from app.api.deps import DbSession, RequireCurator
from app.api.schemas import ApiResponse, ScheduleIn, ScheduleOut
from app.logging import get_logger
from app.services import schedule_service

logger = get_logger(__name__)
router = APIRouter(prefix="/schedules", tags=["schedules"])


@router.get("")
async def list_schedules(
    session: DbSession, user_id: RequireCurator
) -> ApiResponse[list[ScheduleOut]]:
    schedules = await schedule_service.list_schedules(session, user_id=user_id)
    return ApiResponse(data=[ScheduleOut.model_validate(s) for s in schedules])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_schedule(
    body: ScheduleIn, session: DbSession, user_id: RequireCurator
) -> ApiResponse[ScheduleOut]:
    # Length and minimum-interval are enforced by the schema (see ScheduleIn).
    # What is left is the thing a JSON Schema cannot say: a prompt of nothing
    # but whitespace is not a prompt.
    if not body.prompt.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "prompt cannot be empty")

    schedule = await schedule_service.create_schedule(
        session,
        user_id=user_id,
        name=body.name,
        prompt=body.prompt,
        interval_seconds=body.interval_seconds,
    )
    return ApiResponse(data=ScheduleOut.model_validate(schedule))


@router.delete("/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_schedule(
    schedule_id: uuid.UUID, session: DbSession, user_id: RequireCurator
) -> None:
    # False covers "not there" and "not yours" alike — the service scopes by
    # user_id in the WHERE clause, so this cannot accidentally become a 403 that
    # confirms the row exists.
    if not await schedule_service.delete_schedule(
        session, schedule_id=schedule_id, user_id=user_id
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Schedule not found")
