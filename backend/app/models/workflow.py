"""
ORM models for agentic workflows (Phase 3).
Created now so the database schema is future-proof.
Tables will be empty until Phase 3 but the schema is ready.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, Text, ForeignKey, Integer, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Workflow(Base):
    """
    A multi-step agentic workflow execution.
    Phase 3: diagnosis, treatment, research workflows.
    """

    __tablename__ = "workflows"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chat_sessions.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    workflow_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # diagnosis | treatment | research | custom
    status: Mapped[str] = mapped_column(
        String(20), default="pending"
    )  # pending | running | completed | failed | cancelled
    input_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    output_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )

    steps: Mapped[list["WorkflowStep"]] = relationship(
        back_populates="workflow", cascade="all, delete-orphan",
        lazy="selectin", order_by="WorkflowStep.step_number",
    )


class WorkflowStep(Base):
    """A single step in a workflow execution."""

    __tablename__ = "workflow_steps"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflows.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    step_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), default="pending"
    )  # pending | running | done | error | skipped
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    workflow: Mapped["Workflow"] = relationship(back_populates="steps")
    tool_calls: Mapped[list["ToolCall"]] = relationship(
        back_populates="step", cascade="all, delete-orphan", lazy="selectin",
    )


class ToolCall(Base):
    """A tool invocation within a workflow step (for Phase 3 agents)."""

    __tablename__ = "tool_calls"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    step_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_steps.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    tool_name: Mapped[str] = mapped_column(
        String(100), nullable=False
    )  # search_docs | query_graph | check_drugs | calculate | generate_report
    input_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    output_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )

    step: Mapped["WorkflowStep"] = relationship(back_populates="tool_calls")
