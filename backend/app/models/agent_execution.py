"""Persistent control-plane records for Agent execution workflows."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class AgentExecutionSession(Base):
    """Workflow control state, distinct from domain ProcessingRun records."""

    __tablename__ = "agent_execution_sessions"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    copilot_run_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    dataset_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    initial_version_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("dataset_versions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    current_version_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("dataset_versions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    planner_source: Mapped[str] = mapped_column(String(64), nullable=False)
    plan_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    workflow_status: Mapped[str] = mapped_column(String(32), nullable=False, default="PLANNED")
    current_step_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pending_confirmation_step_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    artifacts: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    step_runs: Mapped[list[AgentStepRun]] = relationship(
        back_populates="execution",
        cascade="all, delete-orphan",
        order_by=lambda: AgentStepRun.sequence,
    )


class AgentStepRun(Base):
    """One durable, ordered execution attempt within an Agent workflow."""

    __tablename__ = "agent_step_runs"
    __table_args__ = (
        UniqueConstraint("execution_id", "step_id", name="uq_agent_step_runs_execution_step_id"),
        UniqueConstraint("execution_id", "sequence", name="uq_agent_step_runs_execution_sequence"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    execution_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("agent_execution_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    step_id: Mapped[str] = mapped_column(String(64), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    tool_name: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    requires_confirmation: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    confirmation_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="NOT_REQUIRED"
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_version_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("dataset_versions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    result_version_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("dataset_versions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    input_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    result_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    processing_run_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    execution: Mapped[AgentExecutionSession] = relationship(back_populates="step_runs")