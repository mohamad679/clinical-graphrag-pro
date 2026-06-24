"""phase4 privacy ownership

Revision ID: 20260324_0002
Revises: 20260323_0001
Create Date: 2026-03-24 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260324_0002"
down_revision: Union[str, None] = "20260323_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("chat_sessions", sa.Column("user_id", sa.String(length=100), nullable=True))
    op.create_index(op.f("ix_chat_sessions_user_id"), "chat_sessions", ["user_id"], unique=False)

    op.add_column("documents", sa.Column("user_id", sa.String(length=100), nullable=True))
    op.create_index(op.f("ix_documents_user_id"), "documents", ["user_id"], unique=False)

    op.add_column("medical_images", sa.Column("user_id", sa.String(length=100), nullable=True))
    op.create_index(op.f("ix_medical_images_user_id"), "medical_images", ["user_id"], unique=False)

    op.add_column("workflows", sa.Column("user_id", sa.String(length=100), nullable=True))
    op.create_index(op.f("ix_workflows_user_id"), "workflows", ["user_id"], unique=False)

    op.add_column("user_feedback", sa.Column("user_id", sa.String(length=100), nullable=True))
    op.create_index(op.f("ix_user_feedback_user_id"), "user_feedback", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_user_feedback_user_id"), table_name="user_feedback")
    op.drop_column("user_feedback", "user_id")

    op.drop_index(op.f("ix_workflows_user_id"), table_name="workflows")
    op.drop_column("workflows", "user_id")

    op.drop_index(op.f("ix_medical_images_user_id"), table_name="medical_images")
    op.drop_column("medical_images", "user_id")

    op.drop_index(op.f("ix_documents_user_id"), table_name="documents")
    op.drop_column("documents", "user_id")

    op.drop_index(op.f("ix_chat_sessions_user_id"), table_name="chat_sessions")
    op.drop_column("chat_sessions", "user_id")
