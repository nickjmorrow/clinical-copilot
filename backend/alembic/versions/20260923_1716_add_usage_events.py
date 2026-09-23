"""add usage events

Revision ID: 642b58212076
Revises: 567011b2b065
Create Date: 2026-09-23 17:16:12.907532+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "642b58212076"
down_revision: str | None = "567011b2b065"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "usage_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("kind in ('message', 'tokens')", name="usage_events_kind_check"),
        sa.CheckConstraint("amount >= 0", name="usage_events_amount_check"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "usage_events_kind_created_idx", "usage_events", ["kind", "created_at"], unique=False
    )
    op.create_index(
        "usage_events_user_kind_created_idx",
        "usage_events",
        ["user_id", "kind", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("usage_events_user_kind_created_idx", table_name="usage_events")
    op.drop_index("usage_events_kind_created_idx", table_name="usage_events")
    op.drop_table("usage_events")
