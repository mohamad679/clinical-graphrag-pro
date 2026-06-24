"""
Nightly data-retention tasks for expiring old sessions and related records.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from app.core.config import get_settings
from app.core.database import async_session_factory
from app.models.chat import ChatSession
from app.models.user_feedback import UserFeedback
from app.models.workflow import Workflow


async def purge_expired_sessions() -> dict:
    """Delete sessions older than the configured retention window."""
    settings = get_settings()
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.data_retention_days)

    async with async_session_factory() as db:
        result = await db.execute(select(ChatSession).where(ChatSession.created_at < cutoff))
        sessions = result.scalars().all()
        session_ids = [str(session.id) for session in sessions]

        removed_feedback = 0
        removed_workflows = 0

        if session_ids:
            feedback_rows = await db.execute(
                select(UserFeedback.id)
                .where(UserFeedback.session_id.in_(session_ids))
            )
            workflow_rows = await db.execute(
                select(Workflow.id)
                .where(Workflow.session_id.in_([session.id for session in sessions]))
            )
            removed_feedback = len(feedback_rows.fetchall())
            removed_workflows = len(workflow_rows.fetchall())
            await db.execute(
                delete(UserFeedback).where(UserFeedback.session_id.in_(session_ids))
            )
            await db.execute(
                delete(Workflow).where(Workflow.session_id.in_([session.id for session in sessions]))
            )

        removed_sessions = len(sessions)
        for session in sessions:
            await db.delete(session)

        await db.commit()
        return {
            "cutoff": cutoff.isoformat(),
            "sessions_deleted": removed_sessions,
            "feedback_deleted": removed_feedback,
            "workflows_deleted": removed_workflows,
        }
