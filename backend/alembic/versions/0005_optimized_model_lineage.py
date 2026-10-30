"""Add optimized-model lineage to optimization studies.

Revision ID: 0005_optimized_model_lineage
Revises: 0004_agent_execution_workflow
Create Date: 2026-08-27 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_optimized_model_lineage"
down_revision: str | None = "0004_agent_execution_workflow"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "optimization_studies", sa.Column("baseline_model_id", sa.Uuid(), nullable=True)
    )
    op.add_column(
        "optimization_studies", sa.Column("optimized_model_id", sa.Uuid(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("optimization_studies", "optimized_model_id")
    op.drop_column("optimization_studies", "baseline_model_id")

