"""
ORM model for Human-in-the-Loop (HITL) feedback on AI responses.
"""

import uuid
from datetime import datetime
from sqlalchemy import String, Integer, DateTime, Text, CheckConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class UserFeedback(Base):
    __tablename__ = "user_feedback"
    __table_args__ = (
        CheckConstraint("rating >= 1 AND rating <= 5", name="ck_user_feedback_rating_range"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str | None] = mapped_column(String(100), index=True, nullable=True)
    message_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    session_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    
    # 1-5 star rating where 4-5 is considered positive CSAT.
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    
    # Optional text correction/comment from the user
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": str(self.id),
            "user_id": self.user_id,
            "message_id": self.message_id,
            "session_id": self.session_id,
            "rating": self.rating,
            "comment": self.comment,
            "timestamp": self.timestamp.isoformat(),
        }
