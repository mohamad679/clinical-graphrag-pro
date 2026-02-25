"""
ORM model for Human-in-the-Loop (HITL) feedback on AI responses.
"""

import uuid
from datetime import datetime
from sqlalchemy import String, Integer, DateTime, Text, ForeignKey, Float
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class UserFeedback(Base):
    __tablename__ = "user_feedback"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    message_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    session_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    
    # +1 for helpful/accurate, -1 for inaccurate/unsafe
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    
    # Optional text correction/comment from the user
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": str(self.id),
            "message_id": self.message_id,
            "session_id": self.session_id,
            "rating": self.rating,
            "comment": self.comment,
            "timestamp": self.timestamp.isoformat(),
        }
