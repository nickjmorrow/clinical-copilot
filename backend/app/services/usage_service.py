"""Cost ceilings: how much of the model a user, and everyone, may spend.

Two limits, both off unless configured (`settings.messages_per_hour`,
`settings.daily_token_budget`), and both read from `usage_events` — a ledger
nothing a user can delete touches. Counting from the transcript instead would
let a visitor send, delete the conversation, and send again with the counter
back at zero; see the model's docstring.

Checked when a message is sent, not mid-turn. A turn already running is
allowed to finish, so the daily budget can be overshot by whatever is in
flight when it is reached — which is why it is a ceiling to set comfortably
below the real one, with the provider's own spend limit as the hard stop.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.logging import get_logger
from app.models import UsageEvent

logger = get_logger(__name__)


async def record_message(session: AsyncSession, *, user_id: str) -> None:
    session.add(UsageEvent(user_id=user_id, kind="message", amount=1))
    await session.commit()


async def record_tokens(session: AsyncSession, *, user_id: str, tokens: int) -> None:
    if tokens <= 0:
        return
    session.add(UsageEvent(user_id=user_id, kind="tokens", amount=tokens))
    await session.commit()


async def refusal(
    session: AsyncSession, *, user_id: str, now: datetime | None = None
) -> str | None:
    """Why `user_id` may not send a message right now, or None if they may.

    The message is shown to the person as-is, so it says what happened and
    when it will stop happening — not a status code.
    """
    now = now or datetime.now(UTC)

    if settings.messages_per_hour is not None:
        sent = await session.scalar(
            select(func.count())
            .select_from(UsageEvent)
            .where(
                UsageEvent.user_id == user_id,
                UsageEvent.kind == "message",
                UsageEvent.created_at > now - timedelta(hours=1),
            )
        )
        limit = settings.messages_per_hour
        if (sent or 0) >= limit:
            logger.info("message refused", reason="hourly_limit", user_id=user_id)
            noun = "message" if limit == 1 else "messages"
            return (
                f"You have sent {limit} {noun} in the last hour, which is the limit here. "
                "Try again in a little while."
            )

    if settings.daily_token_budget is not None:
        midnight = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        used = await session.scalar(
            select(func.coalesce(func.sum(UsageEvent.amount), 0)).where(
                UsageEvent.kind == "tokens", UsageEvent.created_at >= midnight
            )
        )
        if (used or 0) >= settings.daily_token_budget:
            logger.info("message refused", reason="daily_budget", tokens_used=int(used or 0))
            return (
                "This demo has used today's budget for the model. It resets at "
                "midnight UTC — please come back then."
            )

    return None
