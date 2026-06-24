"""multimedia pipeline hardening

Revision ID: 20260326_0008
Revises: 20260326_0007
Create Date: 2026-03-26 06:15:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260326_0008"
down_revision: Union[str, None] = "20260326_0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "audio_transcripts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.String(length=100), nullable=True),
        sa.Column("storage_asset_id", sa.Uuid(), nullable=True),
        sa.Column("transcription_job_id", sa.Uuid(), nullable=True),
        sa.Column("filename", sa.String(length=500), nullable=False),
        sa.Column("original_filename", sa.String(length=500), nullable=False),
        sa.Column("mime_type", sa.String(length=255), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("language", sa.String(length=32), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="queued"),
        sa.Column("provider", sa.String(length=100), nullable=True),
        sa.Column("provider_model", sa.String(length=100), nullable=True),
        sa.Column("transcript_text", sa.Text(), nullable=True),
        sa.Column("translated_text", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("retention_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["storage_asset_id"], ["stored_assets.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["transcription_job_id"], ["job_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_audio_transcripts_user_id"), "audio_transcripts", ["user_id"], unique=False)
    op.create_index(op.f("ix_audio_transcripts_storage_asset_id"), "audio_transcripts", ["storage_asset_id"], unique=False)
    op.create_index(op.f("ix_audio_transcripts_transcription_job_id"), "audio_transcripts", ["transcription_job_id"], unique=False)
    op.create_index(op.f("ix_audio_transcripts_status"), "audio_transcripts", ["status"], unique=False)

    with op.batch_alter_table("medical_images", schema=None) as batch_op:
        batch_op.add_column(sa.Column("validation_metadata", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("phi_scrubbed", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("manual_review_required", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("manual_review_status", sa.String(length=30), nullable=False, server_default="pending"))
        batch_op.add_column(sa.Column("last_error", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("analysis_requested_at", sa.DateTime(timezone=True), nullable=True))

    with op.batch_alter_table("image_annotations", schema=None) as batch_op:
        batch_op.add_column(sa.Column("previous_annotation_id", sa.Uuid(), nullable=True))
        batch_op.add_column(sa.Column("version_number", sa.Integer(), nullable=False, server_default="1"))
        batch_op.add_column(sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(sa.Column("corrected_by", sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column("corrected_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("review_status", sa.String(length=30), nullable=False, server_default="ai_generated"))
        batch_op.add_column(sa.Column("metadata", sa.JSON(), nullable=True))
        batch_op.create_index(batch_op.f("ix_image_annotations_previous_annotation_id"), ["previous_annotation_id"], unique=False)
        batch_op.create_foreign_key(
            "fk_image_annotations_previous_annotation_id",
            "image_annotations",
            ["previous_annotation_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("image_annotations", schema=None) as batch_op:
        batch_op.drop_constraint("fk_image_annotations_previous_annotation_id", type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_image_annotations_previous_annotation_id"))
        batch_op.drop_column("metadata")
        batch_op.drop_column("review_status")
        batch_op.drop_column("deleted_at")
        batch_op.drop_column("corrected_at")
        batch_op.drop_column("corrected_by")
        batch_op.drop_column("is_current")
        batch_op.drop_column("version_number")
        batch_op.drop_column("previous_annotation_id")

    with op.batch_alter_table("medical_images", schema=None) as batch_op:
        batch_op.drop_column("analysis_requested_at")
        batch_op.drop_column("last_error")
        batch_op.drop_column("manual_review_status")
        batch_op.drop_column("manual_review_required")
        batch_op.drop_column("phi_scrubbed")
        batch_op.drop_column("validation_metadata")

    op.drop_index(op.f("ix_audio_transcripts_status"), table_name="audio_transcripts")
    op.drop_index(op.f("ix_audio_transcripts_transcription_job_id"), table_name="audio_transcripts")
    op.drop_index(op.f("ix_audio_transcripts_storage_asset_id"), table_name="audio_transcripts")
    op.drop_index(op.f("ix_audio_transcripts_user_id"), table_name="audio_transcripts")
    op.drop_table("audio_transcripts")
