"""add browse to query audit via check

Revision ID: 567011b2b065
Revises: 8e146dede379
Create Date: 2026-09-22 23:10:36.493379+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "567011b2b065"
down_revision: str | None = "8e146dede379"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Autogenerate saw nothing here, the same blind spot AGENTS.md documents
    # for a partial index's WHERE clause: it compares a CHECK constraint by
    # name, not by the expression inside it, so a widened `via in (...)` list
    # produces an empty migration unless written by hand.
    op.drop_constraint("query_audit_via_check", "query_audit", type_="check")
    op.create_check_constraint(
        "query_audit_via_check",
        "query_audit",
        "via in ('tool', 'cohort', 'explain', 'export', 'preview', 'browse')",
    )


def downgrade() -> None:
    op.drop_constraint("query_audit_via_check", "query_audit", type_="check")
    op.create_check_constraint(
        "query_audit_via_check",
        "query_audit",
        "via in ('tool', 'cohort', 'explain', 'export', 'preview')",
    )
