"""Shared FastAPI dependencies."""

from collections.abc import Awaitable, Callable
from functools import lru_cache
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import DEV_USER_ID, settings
from app.db import get_session
from app.logging import get_logger
from app.services import authz_service

logger = get_logger(__name__)

# auto_error=False so a missing header reaches the code below, which can decide
# whether that is a 401 or simply the dev user.
_bearer = HTTPBearer(auto_error=False)


@lru_cache(maxsize=1)
def _jwks_client() -> jwt.PyJWKClient:
    """The provider's public keys.

    PyJWKClient handles fetching, caching, and picking the key matching the
    token's `kid` — which matters because providers rotate keys without warning
    and a pinned key is an outage with a date on it.
    """
    return jwt.PyJWKClient(settings.jwks_url, cache_keys=True)


def _unauthorized(reason: str) -> HTTPException:
    logger.info("auth rejected", reason=reason)
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> str:
    """Who is making this request.

    **The auth seam**, in three modes, most specific first:

    - An OIDC issuer is configured and the request carries a token: verify it
      against that provider's JWKS, and its `sub` is the user.
    - Public mode (`settings.visitor_mode`): the anonymous visitor id
      `VisitorMiddleware` put on the request — one per browser, no roles.
    - Neither: with no issuer configured, the one dev user, and the app runs
      with no accounts at all. With an issuer and no token, a 401.

    Nothing downstream changes in any mode, because everything downstream only
    ever wanted a user id. That id goes straight into `conversations.user_id`
    and therefore into the WHERE clause of every query — which is the property
    that makes switching modes safe rather than the beginning of an audit.
    """
    if settings.auth_enabled and credentials is not None:
        return _verified_subject(credentials)

    visitor: object = getattr(request.state, "visitor_id", None)
    if isinstance(visitor, str):
        return visitor

    if not settings.auth_enabled:
        return DEV_USER_ID
    raise _unauthorized("no_bearer_token")


def _verified_subject(credentials: HTTPAuthorizationCredentials) -> str:
    """The `sub` of a token the configured issuer signed, or a 401."""

    try:
        signing_key = _jwks_client().get_signing_key_from_jwt(credentials.credentials)
        claims = jwt.decode(
            credentials.credentials,
            signing_key.key,
            # Named explicitly. Accepting whatever the token asks for is the
            # algorithm-confusion bug — a token signed with the public key as an
            # HMAC secret verifies happily against a permissive decoder.
            algorithms=["RS256", "ES256"],
            audience=settings.oidc_audience or None,
            issuer=settings.oidc_issuer,
            options={"require": ["exp", "sub"]},
        )
    except jwt.PyJWTError as exc:
        # Deliberately not echoed to the client: the distinction between
        # "expired", "wrong audience" and "bad signature" is useful to us in a
        # log and useful to an attacker in a response body.
        raise _unauthorized(type(exc).__name__) from exc

    subject = claims.get("sub")
    if not subject:
        raise _unauthorized("no_subject")
    return str(subject)


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
