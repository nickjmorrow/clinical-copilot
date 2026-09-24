"""A question worth asking again — SEMANTIC_LAYER.md § 17.

Scoped by `user_id`, the same discipline `conversations` and `schedules`
already follow: any authenticated user manages their own, no special role
needed. Running one goes through `clinical_query_service.answer_question`
exactly like the model's tool does — resolved fresh against whatever the
definitions say right now, audited with `via="cohort"`, never served from a
stored answer. Saving the rows instead would be an answer cache, which this
project refuses on purpose; see `app/services/saved_question_service.py` and
AGENTS.md's "no answer caching" line.
"""

import uuid

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, DbSession
from app.api.schemas import (
    ApiResponse,
    SavedQuestionCreateIn,
    SavedQuestionOut,
    SavedQuestionRunOut,
    to_saved_question_run_out,
)
from app.services import clinical_query_service, saved_question_service

router = APIRouter(prefix="/saved-questions", tags=["saved-questions"])


@router.get("")
async def list_saved_questions(
    session: DbSession, user_id: CurrentUser
) -> ApiResponse[list[SavedQuestionOut]]:
    rows = await saved_question_service.list_saved_questions(session, user_id=user_id)
    return ApiResponse(data=[SavedQuestionOut.model_validate(row) for row in rows])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_saved_question(
    body: SavedQuestionCreateIn, session: DbSession, user_id: CurrentUser
) -> ApiResponse[SavedQuestionOut]:
    try:
        row = await saved_question_service.create_saved_question(
            session,
            user_id=user_id,
            name=body.name,
            terms=body.terms,
            measures=body.measures,
            group_by=body.group_by,
        )
    except ValueError as invalid:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(invalid)) from invalid
    return ApiResponse(data=SavedQuestionOut.model_validate(row))


@router.delete("/{question_id}")
async def delete_saved_question(
    question_id: uuid.UUID, session: DbSession, user_id: CurrentUser
) -> ApiResponse[None]:
    await saved_question_service.delete_saved_question(
        session, user_id=user_id, question_id=question_id
    )
    return ApiResponse(data=None)


@router.post("/{question_id}/run")
async def run_saved_question(
    question_id: uuid.UUID, session: DbSession, user_id: CurrentUser
) -> ApiResponse[SavedQuestionRunOut]:
    row = await saved_question_service.get_saved_question(
        session, user_id=user_id, question_id=question_id
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No saved question with that id.")

    # The same row-level scope a chat turn would carry — a saved question run
    # through this route is not a way around it.
    asker = await clinical_query_service.build_asker(session, user_id=user_id)
    answer = await clinical_query_service.answer_question(
        session,
        asker,
        question=f"(saved question) {row.name}",
        terms=list(row.terms),
        measures=list(row.measures),
        group_by=list(row.group_by),
        via="cohort",
    )
    return ApiResponse(data=to_saved_question_run_out(answer))
