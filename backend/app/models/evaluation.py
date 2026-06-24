"""
ORM models for evaluation metric storage.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Integer, DateTime, JSON, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class EvaluationRun(Base):
    """Storage for different evaluation metrics."""

    __tablename__ = "evaluation_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    evaluation_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # e.g., 'ragas', 'adjudicator'
    tenant_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    user_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    dataset_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    
    # Store metrics like Faithfulness, Precision, Recall as JSON
    metrics: Mapped[dict | None] = mapped_column(
        JSON, nullable=False, default=dict
    )
    
    # Optional metadata like llm model used, time taken
    metadata_: Mapped[dict | None] = mapped_column(
        "metadata", JSON, nullable=True, default=dict
    )
