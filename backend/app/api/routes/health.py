from fastapi import APIRouter
from sqlalchemy import text

from app.api.deps import DbSession
from app.api.schemas import ApiResponse

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(session: DbSession) -> ApiResponse[dict[str, str]]:
    """Liveness + database reachability.

    Actually touches the database: a health check that only proves the web
    process is running will happily report green while every request 500s.
    """
    await session.execute(text("select 1"))
    return ApiResponse(data={"status": "ok", "database": "ok"})
