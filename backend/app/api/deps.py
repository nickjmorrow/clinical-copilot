"""Shared FastAPI dependencies."""

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import DEV_USER_ID
from app.db import get_session
from app.logging import get_logger
from app.services import authz_service

logger = get_logger(__name__)


async def get_current_user(request: Request) -> str:
    """Who is making this request.

    **The identity seam**, in two modes:

    - Public mode (`settings.visitor_mode`): the anonymous visitor id
      `VisitorMiddleware` put on the request — one per browser, no roles.
    - Otherwise the one dev user, and the app runs with no accounts at all.

    There is no sign-in. Nothing downstream would change if there were, because
    everything downstream only ever wanted a user id. That id goes straight
    into `conversations.user_id` and therefore into the WHERE clause of every
    query — which is the property that makes adding a real identity provider
    one function here rather than the beginning of an audit.
    """
    visitor: object = getattr(request.state, "visitor_id", None)
    if isinstance(visitor, str):
        return visitor
    return DEV_USER_ID


CurrentUser = Annotated[str, Depends(get_current_user)]
DbSession = Annotated[AsyncSession, Depends(get_session)]


def require_any_role(*roles: str) -> Callable[[CurrentUser, DbSession], Awaitable[str]]:
    """A dependency factory: the caller must hold at least one of `roles`.

    A factory rather than one dependency per role, because the set of routes
    that want "curator or auditor" (read the authoring surface) is different
    from the set that wants "curator only" (write to it), and spelling both
    out as fixed dependencies would mean a third combination is a second
    factory anyway. `user_id` is returned rather than discarded so a route can
    depend on this alone instead of stacking it with `CurrentUser`.
    """

    async def check(user_id: CurrentUser, session: DbSession) -> str:
        held = await authz_service.get_roles(session, user_id=user_id)
        if not held.intersection(roles):
            logger.info("role check failed", user_id=user_id, needs=list(roles), has=list(held))
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"requires one of the following roles: {list(roles)}",
            )
        return user_id

    return check


# Read the authoring surface (definitions with their logic, history, model
# checks): a curator reviewing what they can edit, or an auditor reviewing
# what is live, for the same reason the `/clinical/context` panel withholds
# `logic` from the model but not from a person. Write to it: curator only.
RequireReviewer = Annotated[
    str, Depends(require_any_role(authz_service.CURATOR, authz_service.AUDITOR))
]
RequireCurator = Annotated[str, Depends(require_any_role(authz_service.CURATOR))]
