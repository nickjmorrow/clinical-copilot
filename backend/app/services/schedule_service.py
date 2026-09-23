"""Scheduled agent business logic.

The same contract as `conversation_service`: routes validate, authorize and
shape a response; everything a second caller would need lives here. The second
caller is not hypothetical — the worker already reads `schedules` to expand due
rows, and a schedules UI or a `seed` command would be the third and fourth.

Every function takes an explicit `session`.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging import get_logger
from app.models import Schedule

logger = get_logger(__name__)

DEFAULT_NAME = "Untitled schedule"


async def list_schedules(session: AsyncSession, *, user_id: str) -> list[Schedule]:
    result = await session.execute(
        select(Schedule).where(Schedule.user_id == user_id).order_by(Schedule.created_at)
    )
    return list(result.scalars().all())


async def create_schedule(
    session: AsyncSession,
    *,
    user_id: str,
    name: str,
    prompt: str,
    interval_seconds: int,
) -> Schedule:
    """Create a schedule. It is due immediately — `next_run_at` defaults to now.

    Running once on creation rather than one interval later is deliberate: a
    daily agent you cannot see the output of for 24 hours is one you cannot
    iterate on.
    """
    schedule = Schedule(
        user_id=user_id,
        name=name.strip() or DEFAULT_NAME,
        prompt=prompt.strip(),
        interval_seconds=interval_seconds,
    )
    session.add(schedule)
    await session.commit()
    await session.refresh(schedule)

    logger.info(
        "schedule created",
        schedule_id=str(schedule.id),
        user_id=user_id,
        interval_seconds=interval_seconds,
    )
    return schedule


async def delete_schedule(session: AsyncSession, *, schedule_id: uuid.UUID, user_id: str) -> bool:
    """Delete one schedule. False when it does not exist *or* is not yours.

    Scoped in the WHERE clause, like every other query: someone else's schedule
    must be indistinguishable from one that was never there. The caller turns
    False into a 404 and cannot accidentally turn it into a 403, which would
    confirm the row exists.
    """
    result = await session.execute(
        select(Schedule).where(Schedule.id == schedule_id, Schedule.user_id == user_id)
    )
    schedule = result.scalar_one_or_none()
    if schedule is None:
        return False

    await session.delete(schedule)
    await session.commit()
    logger.info("schedule deleted", schedule_id=str(schedule_id), user_id=user_id)
    return True
