"""document pipeline hardening

Revision ID: 20260326_0005
Revises: 20260326_0004
Create Date: 2026-03-26 00:05:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260326_0005"
down_revision: Union[str, None] = "20260326_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("documents", schema=None) as batch_op:
        batch_op.add_column(sa.Column("previous_version_id", sa.Uuid(), nullable=True))
        batch_op.add_column(sa.Column("version_group_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("version_number", sa.Integer(), nullable=False, server_default="1"))
        batch_op.add_column(sa.Column("is_latest_version", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(sa.Column("duplicate_policy", sa.String(length=20), nullable=False, server_default="reuse"))
        batch_op.add_column(sa.Column("processing_stage", sa.String(length=32), nullable=False, server_default="uploaded"))
        batch_op.add_column(sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_index(batch_op.f("ix_documents_previous_version_id"), ["previous_version_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_documents_version_group_id"), ["version_group_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_documents_is_latest_version"), ["is_latest_version"], unique=False)
        batch_op.create_index(batch_op.f("ix_documents_processing_stage"), ["processing_stage"], unique=False)
        batch_op.create_foreign_key(
            "fk_documents_previous_version_id_documents",
            "documents",
            ["previous_version_id"],
            ["id"],
            ondelete="SET NULL",
        )

    with op.batch_alter_table("document_contents", schema=None) as batch_op:
        batch_op.add_column(sa.Column("page_metadata", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("scanned_pdf_detected", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("ocr_status", sa.String(length=30), nullable=False, server_default="not_requested"))

    with op.batch_alter_table("document_chunks", schema=None) as batch_op:
        batch_op.add_column(sa.Column("page_start", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("page_end", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("source_offset_start", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("source_offset_end", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("embedding_version", sa.String(length=255), nullable=True))

    op.execute("UPDATE documents SET version_number = 1 WHERE version_number IS NULL")
    op.execute("UPDATE documents SET duplicate_policy = 'reuse' WHERE duplicate_policy IS NULL")
    op.execute("UPDATE documents SET processing_stage = 'uploaded' WHERE processing_stage IS NULL")
    op.execute("UPDATE documents SET is_latest_version = 1 WHERE is_latest_version IS NULL")
    op.execute("UPDATE documents SET version_group_id = CAST(id AS TEXT) WHERE version_group_id IS NULL")


def downgrade() -> None:
    with op.batch_alter_table("document_chunks", schema=None) as batch_op:
        batch_op.drop_column("embedding_version")
        batch_op.drop_column("source_offset_end")
        batch_op.drop_column("source_offset_start")
        batch_op.drop_column("page_end")
        batch_op.drop_column("page_start")

    with op.batch_alter_table("document_contents", schema=None) as batch_op:
        batch_op.drop_column("ocr_status")
        batch_op.drop_column("scanned_pdf_detected")
        batch_op.drop_column("page_metadata")

    with op.batch_alter_table("documents", schema=None) as batch_op:
        batch_op.drop_constraint("fk_documents_previous_version_id_documents", type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_documents_processing_stage"))
        batch_op.drop_index(batch_op.f("ix_documents_is_latest_version"))
        batch_op.drop_index(batch_op.f("ix_documents_version_group_id"))
        batch_op.drop_index(batch_op.f("ix_documents_previous_version_id"))
        batch_op.drop_column("superseded_at")
        batch_op.drop_column("processing_stage")
        batch_op.drop_column("duplicate_policy")
        batch_op.drop_column("is_latest_version")
        batch_op.drop_column("version_number")
        batch_op.drop_column("version_group_id")
        batch_op.drop_column("previous_version_id")
