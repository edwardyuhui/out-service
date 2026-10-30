"""Persist the Copilot run that created an Agent execution session.

Revision ID: 0006_agent_copilot_link
Revises: 0005_optimized_model_lineage
Create Date: 2026-08-28 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_agent_copilot_link"
down_revision: str | None = "0005_optimized_model_lineage"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_execution_sessions", sa.Column("copilot_run_id", sa.Uuid(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("agent_execution_sessions", "copilot_run_id")