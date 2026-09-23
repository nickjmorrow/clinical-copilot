"""Questions worth asking again.

A saved question is its resolved parts — terms, measures, group-by names —
never the SQL and never the rows. See `SavedQuestion` in `app/models.py`:
re-running it goes through `clinical_query_service.answer_question` like any
other question, so an edited threshold is picked up rather than frozen, and
the run is audited like any other. Saving the rows instead would be an answer
cache, which this project refuses on purpose — see CONVENTIONS.md § Choosing a
model and the "no answer caching" line in SEMANTIC_LAYER.md.

Scoped by `user_id` in the WHERE clause, the same discipline every other
per-user table in this codebase follows: a saved question belonging to someone
else is indistinguishable from one that does not exist.
"""

import uuid
from collections.abc import Sequence

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging import get_logger
from app.models import SavedQuestion

logger = get_logger(__name__)


async def list_saved_questions(session: AsyncSession, *, user_id: str) -> list[SavedQuestion]:
    result = await session.execute(
        select(SavedQuestion)
        .where(SavedQuestion.user_id == user_id)
        .order_by(SavedQuestion.created_at.desc())
    )
    return list(result.scalars().all())


async def get_saved_question(
    session: AsyncSession, *, user_id: str, question_id: uuid.UUID
) -> SavedQuestion | None:
    result = await session.execute(
        select(SavedQuestion).where(
            SavedQuestion.id == question_id, SavedQuestion.user_id == user_id
        )
    )
    return result.scalar_one_or_none()


async def create_saved_question(
    session: AsyncSession,
    *,
    user_id: str,
    name: str,
    terms: Sequence[str],
    measures: Sequence[str] = (),
    group_by: Sequence[str] = (),
) -> SavedQuestion:
    if not terms:
        message = "a saved question needs at least one term"
        raise ValueError(message)
    row = SavedQuestion(
        user_id=user_id,
        name=name,
        terms=list(terms),
        measures=list(measures),
        group_by=list(group_by),
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    logger.info("saved question created", user_id=user_id, name=name)
    return row


async def delete_saved_question(
    session: AsyncSession, *, user_id: str, question_id: uuid.UUID
) -> None:
    await session.execute(
        delete(SavedQuestion).where(
            SavedQuestion.id == question_id, SavedQuestion.user_id == user_id
        )
    )
    await session.commit()
    logger.info("saved question deleted", user_id=user_id, question_id=str(question_id))
