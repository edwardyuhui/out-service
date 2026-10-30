"""Create persistent Agent execution workflow tables.

Revision ID: 0004_agent_execution_workflow
Revises: 0003_optimization_and_memory
Create Date: 2026-08-25 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_agent_execution_workflow"
down_revision: str | None = "0003_optimization_and_memory"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_execution_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("initial_version_id", sa.Uuid(), nullable=False),
        sa.Column("current_version_id", sa.Uuid(), nullable=False),
        sa.Column("planner_source", sa.String(length=64), nullable=False),
        sa.Column("plan_json", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column(
            "workflow_status",
            sa.String(length=32),
            server_default=sa.text("'PLANNED'"),
            nullable=False,
        ),
        sa.Column("current_step_id", sa.String(length=64), nullable=True),
        sa.Column("pending_confirmation_step_id", sa.String(length=64), nullable=True),
        sa.Column("artifacts", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.String(length=1024), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["initial_version_id"], ["dataset_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["current_version_id"], ["dataset_versions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_agent_execution_sessions_dataset_id", "agent_execution_sessions", ["dataset_id"]
    )
    op.create_index(
        "ix_agent_execution_sessions_initial_version_id",
        "agent_execution_sessions",
        ["initial_version_id"],
    )
    op.create_index(
        "ix_agent_execution_sessions_current_version_id",
        "agent_execution_sessions",
        ["current_version_id"],
    )

    op.create_table(
        "agent_step_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("step_id", sa.String(length=64), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("tool_name", sa.String(length=80), nullable=False),
        sa.Column(
            "status", sa.String(length=32), server_default=sa.text("'PENDING'"), nullable=False
        ),
        sa.Column("requires_confirmation", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column(
            "confirmation_status",
            sa.String(length=32),
            server_default=sa.text("'NOT_REQUIRED'"),
            nullable=False,
        ),
        sa.Column("attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("source_version_id", sa.Uuid(), nullable=True),
        sa.Column("result_version_id", sa.Uuid(), nullable=True),
        sa.Column("input_payload", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("result_payload", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("processing_run_ids", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.String(length=1024), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["execution_id"], ["agent_execution_sessions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_version_id"], ["dataset_versions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["result_version_id"], ["dataset_versions.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("execution_id", "step_id", name="uq_agent_step_runs_execution_step_id"),
        sa.UniqueConstraint("execution_id", "sequence", name="uq_agent_step_runs_execution_sequence"),
    )
    op.create_index("ix_agent_step_runs_execution_id", "agent_step_runs", ["execution_id"])
    op.create_index(
        "ix_agent_step_runs_source_version_id", "agent_step_runs", ["source_version_id"]
    )
    op.create_index(
        "ix_agent_step_runs_result_version_id", "agent_step_runs", ["result_version_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_agent_step_runs_result_version_id", table_name="agent_step_runs")
    op.drop_index("ix_agent_step_runs_source_version_id", table_name="agent_step_runs")
    op.drop_index("ix_agent_step_runs_execution_id", table_name="agent_step_runs")
    op.drop_table("agent_step_runs")
    op.drop_index(
        "ix_agent_execution_sessions_current_version_id", table_name="agent_execution_sessions"
    )
    op.drop_index(
        "ix_agent_execution_sessions_initial_version_id", table_name="agent_execution_sessions"
    )
    op.drop_index("ix_agent_execution_sessions_dataset_id", table_name="agent_execution_sessions")
    op.drop_table("agent_execution_sessions")
