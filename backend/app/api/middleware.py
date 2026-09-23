"""Request context and access logging.

**Pure ASGI, not `BaseHTTPMiddleware`.** The convenient base class buffers the
response body to hand it to you as one object, which for a Server-Sent Events
endpoint means the stream arrives all at once at the end — the exact failure the
`X-Accel-Buffering` header elsewhere exists to prevent. Forty lines of ASGI
avoids it entirely.

The request id is bound into `structlog.contextvars`, so every log line for the
rest of the request carries it without a single call site passing it along. That
machinery was already wired up in `logging.py` — `merge_contextvars` has always
been in the processor chain — and nothing had ever bound anything to it.
"""

import re
import secrets
import time
import uuid
from typing import Any

import structlog
from starlette.datastructures import MutableHeaders
from starlette.requests import cookie_parser
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import settings
from app.logging import get_logger

logger = get_logger(__name__)

REQUEST_ID_HEADER = "x-request-id"


def new_request_id() -> str:
    return uuid.uuid4().hex[:16]


class RequestContextMiddleware:
    """Tag every request, log both ends of it, and hand the id back."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {k.decode(): v.decode() for k, v in scope.get("headers", [])}
        # Honour an id from upstream — a load balancer, another service — so one
        # trace survives more than one hop. Mint one otherwise.
        request_id = headers.get(REQUEST_ID_HEADER) or new_request_id()

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        method: str = scope.get("method", "")
        path: str = scope.get("path", "")
        started = time.perf_counter()
        logger.info("request started", method=method, path=path)

        async def send_with_context(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message).append(REQUEST_ID_HEADER, request_id)

                # Timed to the first byte, not to the last. For a stream the
                # time to the last byte is how long someone watched it, which is
                # not latency and would make every SSE request look like an
                # outage.
                logger.info(
                    "request finished",
                    method=method,
                    path=path,
                    status_code=message["status"],
                    duration_ms=round((time.perf_counter() - started) * 1000, 1),
                )
            await send(message)

        try:
            await self.app(scope, receive, send_with_context)
        except Exception:
            logger.exception("request failed", method=method, path=path)
            raise
        finally:
            structlog.contextvars.clear_contextvars()


def current_request_id() -> str | None:
    """The id bound to this request, for anything that needs to carry it further.

    Used when enqueueing a task: the id is stored on the row so the worker can
    re-bind it and one turn stays greppable across two processes.
    """
    bound: dict[str, Any] = structlog.contextvars.get_contextvars()
    value = bound.get("request_id")
    return str(value) if value else None


VISITOR_COOKIE = "visitor"
# `secrets.token_urlsafe(24)` is 32 characters of this alphabet. Anything else
# in the cookie is ignored and replaced, so a hand-edited cookie cannot pick
# its own identity — and the `visitor:` prefix below means no value of it can
# ever equal a real user id, the dev user's included.
_VISITOR_TOKEN = re.compile(r"^[A-Za-z0-9_-]{32}$")
_VISITOR_MAX_AGE = 60 * 60 * 24 * 365


def _visitor_token(scope: Scope) -> str | None:
    for name, value in scope.get("headers", []):
        if name == b"cookie":
            token = cookie_parser(value.decode("latin-1")).get(VISITOR_COOKIE)
            if token and _VISITOR_TOKEN.fullmatch(token):
                return token
    return None


class VisitorMiddleware:
    """Give each browser an identity of its own, when `settings.visitor_mode`.

    A random id in an HttpOnly cookie, minted on the first request that
    arrives without one and read on every request after. It becomes the user
    id (`visitor:<token>`), and because every query is already scoped by user
    id in its WHERE clause, a visitor's conversations and saved questions are
    theirs alone with no other change anywhere. It is an unguessable bearer
    token, not an account: clear the cookie and you are a new visitor.

    Pure ASGI for the same reason as `RequestContextMiddleware`: the cookie is
    added to the response head, and the body — an SSE stream, often — passes
    through untouched.

    The first page load sends several requests at once, before any of them
    has a cookie to send back, so each mints its own and the last to land
    wins. Harmless, because those first requests are all reads; by the time
    anyone can type, the browser has settled on one.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not settings.visitor_mode:
            await self.app(scope, receive, send)
            return

        token = _visitor_token(scope)
        is_new = token is None
        if token is None:
            token = secrets.token_urlsafe(24)
        scope.setdefault("state", {})["visitor_id"] = f"visitor:{token}"

        if not is_new:
            await self.app(scope, receive, send)
            return

        cookie = (
            f"{VISITOR_COOKIE}={token}; Max-Age={_VISITOR_MAX_AGE}; Path=/; HttpOnly; SameSite=Lax"
        )
        if settings.visitor_cookie_secure:
            cookie += "; Secure"

        async def send_with_cookie(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message).append("set-cookie", cookie)
            await send(message)

        await self.app(scope, receive, send_with_cookie)
