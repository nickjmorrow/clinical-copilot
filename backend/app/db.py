"""Async engine and session factory.

Async all the way down (asyncpg driver, AsyncSession, `async def` routes) is
correct here because we run under native uvicorn. If you ever deploy this
behind a WSGI shim or gevent workers, that stops being true — an async handler
in a sync worker blocks the whole event loop on every query.
"""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

engine = create_async_engine(
    settings.database_url,
    # Surfaces a dead connection as a retry instead of an error after the
    # database restarts — which it will, every time you edit schema.sql.
    pool_pre_ping=True,
)

SessionFactory = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding one session per request.

    Commit explicitly in the service layer. This only guarantees the session is
    closed, including when the handler raises.
    """
    async with SessionFactory() as session:
        yield session
