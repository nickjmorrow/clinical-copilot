"""Application entry point.

Deliberately thin: configure logging, mount middleware, include routers. Any
logic that shows up here belongs in a service.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.middleware import RequestContextMiddleware, VisitorMiddleware
from app.api.routes import (
    access,
    audit,
    clinical,
    cohort,
    conversations,
    definitions,
    health,
    saved_questions,
    schedules,
)
from app.bus import bus
from app.config import settings
from app.db import engine
from app.logging import configure_logging, get_logger

configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
# `_app` is handed to us by FastAPI and not needed; the underscore says so.
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    logger.info("app starting", model=settings.anthropic_model)
    # One LISTEN connection for the process, shared by every open stream.
    await bus.start()
    yield
    await bus.stop()
    # Without this, shutdown leaves connections open and the container takes
    # its full grace period to die on every restart.
    await engine.dispose()
    logger.info("app stopped")


app = FastAPI(title="Clinical Copilot", version="0.1.0", lifespan=lifespan)

# Only needed if you run the frontend outside Docker against this directly. In
# the compose setup Vite proxies /api, so requests are same-origin and this
# never fires.
# Inside the request context, so the visitor it identifies is logged with the
# request id. A no-op unless `settings.visitor_mode`.
app.add_middleware(VisitorMiddleware)

# Outermost, so its context is bound before anything else runs and its access
# log sees the status CORS or a handler actually produced.
app.add_middleware(RequestContextMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api")
app.include_router(clinical.router, prefix="/api")
app.include_router(cohort.router, prefix="/api")
app.include_router(definitions.router, prefix="/api")
app.include_router(conversations.router, prefix="/api")
app.include_router(schedules.router, prefix="/api")
app.include_router(saved_questions.router, prefix="/api")
app.include_router(access.router, prefix="/api")
app.include_router(audit.router, prefix="/api")


@app.exception_handler(Exception)
async def unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
    """Turn an unhandled error into one log line and one shaped response.

    Without this, Starlette returns a bare 500 with nothing in the log that
    structlog ever saw — so the one class of failure you most need to find out
    about is the one that leaves no record. `exc_info` puts the traceback where
    the request id already is.
    """
    logger.error("unhandled error", path=request.url.path, exc_info=exc)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
