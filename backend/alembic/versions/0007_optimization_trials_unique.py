"""Enforce one row per (study, trial_number) in optimization_trials at the database level.

``optimization_service._persist_study`` already guarantees this in application code by
deleting a study's existing trial rows before re-inserting the fresh set, so this
constraint should never fire in normal operation. It exists as a backstop against a future
concurrent write (a retried worker job, a second writer) silently producing two rows for
the same trial instead of failing loudly.

Revision ID: 0007_optimization_trials_unique
Revises: 0006_agent_copilot_link
Create Date: 2026-09-03 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007_optimization_trials_unique"
down_revision: str | None = "0006_agent_copilot_link"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

CONSTRAINT_NAME = "uq_optimization_trials_study_id_trial_number"


def upgrade() -> None:
    op.create_unique_constraint(
        CONSTRAINT_NAME,
        "optimization_trials",
        ["study_id", "trial_number"],
    )


def downgrade() -> None:
    op.drop_constraint(CONSTRAINT_NAME, "optimization_trials", type_="unique")
