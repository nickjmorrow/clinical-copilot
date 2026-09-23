"""Who may do what, and which rows they may see.

`user_roles` is a table both processes can read rather than claims read off a
token, because the worker has no token: it answers a clinical question on
behalf of whoever owns the conversation and needs the same answer the API
would give. See `UserRole` in `app/models.py`.

**This is the seam, not the policy.** One hardcoded user has no need of a
permission model, so this module proves the shape rather than implementing
one: `ensure_dev_user` gives the dev user every role and an unconfined scope,
which is what keeps `docker compose up` working with nobody locked out of
anything. Turning it into something real is the two-environment-variable
change CONVENTIONS.md § Authentication already describes for `get_current_user` —
this is its clinical-authorization counterpart.

`scope_states` is row-level access in its smallest honest form: a list of
states a user's queries are confined to, applied in the WHERE clause by
`app/clinical/assembler.scope_condition`, with `None` meaning unconfined.
"""

from collections.abc import Sequence
from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession

from app.logging import get_logger
from app.models import UserRole

logger = get_logger(__name__)

# What a role may do. Enforced by `require_any_role` in api/deps.py checking
# membership; this module only says what a user has, not what a role permits.
ANALYST: Final = "analyst"
CURATOR: Final = "curator"
AUDITOR: Final = "auditor"
ROLES: Final = (ANALYST, CURATOR, AUDITOR)


async def get_roles(session: AsyncSession, *, user_id: str) -> frozenset[str]:
    """A user's roles. Empty — not an error — for a user with no row: the
    absence of a grant is the default-deny state, not an exceptional one."""
    row = await session.get(UserRole, user_id)
    if row is None:
        return frozenset()
    return frozenset(str(role) for role in row.roles)


async def get_scope_states(session: AsyncSession, *, user_id: str) -> list[str] | None:
    """The states a user's clinical queries are confined to. `None` is
    unconfined — the state for a user with no row, same reasoning as
    `get_roles`: no grant recorded means no restriction was ever configured,
    not that the widest one should apply by default in the other direction."""
    row = await session.get(UserRole, user_id)
    if row is None or row.scope_states is None:
        return None
    return [str(state) for state in row.scope_states]


async def set_roles(
    session: AsyncSession, *, user_id: str, roles: Sequence[str], scope_states: Sequence[str] | None
) -> UserRole:
    """Upsert one user's roles and scope. Idempotent: the seed calls it on
    every run, and so does saving a scope in "Your access"."""
    unknown = [role for role in roles if role not in ROLES]
    if unknown:
        message = f"unknown role(s) {unknown}; expected one of {list(ROLES)}"
        raise ValueError(message)

    row = await session.get(UserRole, user_id)
    if row is None:
        row = UserRole(user_id=user_id)
        session.add(row)
    row.roles = list(roles)
    row.scope_states = list(scope_states) if scope_states is not None else None
    await session.commit()
    await session.refresh(row)
    logger.info("user roles set", user_id=user_id, roles=list(roles))
    return row


async def ensure_dev_user(session: AsyncSession, *, user_id: str) -> UserRole:
    """Give the dev user every role and no scope restriction.

    Called by the seed, every load. Idempotent — a reload should not need a
    second thought about who can see what, the same way reseeding is a no-op
    unless `--reset` is passed.
    """
    return await set_roles(session, user_id=user_id, roles=ROLES, scope_states=None)
