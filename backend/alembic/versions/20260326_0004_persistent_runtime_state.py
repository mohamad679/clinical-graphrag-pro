"""persistent runtime state

Revision ID: 20260326_0004
Revises: 20260326_0003
Create Date: 2026-03-26 00:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260326_0004"
down_revision: Union[str, None] = "20260326_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "stored_assets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.String(length=100), nullable=True),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("provider", sa.String(length=30), nullable=False),
        sa.Column("bucket", sa.String(length=255), nullable=False),
        sa.Column("object_key", sa.String(length=1024), nullable=False),
        sa.Column("original_filename", sa.String(length=500), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("encryption_status", sa.String(length=30), nullable=False),
        sa.Column("storage_metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("object_key"),
    )
    op.create_index(op.f("ix_stored_assets_owner_user_id"), "stored_assets", ["owner_user_id"], unique=False)
    op.create_index(op.f("ix_stored_assets_category"), "stored_assets", ["category"], unique=False)
    op.create_index(op.f("ix_stored_assets_checksum"), "stored_assets", ["checksum"], unique=False)

    op.create_table(
        "job_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_type", sa.String(length=50), nullable=False),
        sa.Column("entity_type", sa.String(length=50), nullable=True),
        sa.Column("entity_id", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.String(length=100), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_job_runs_job_type"), "job_runs", ["job_type"], unique=False)
    op.create_index(op.f("ix_job_runs_entity_type"), "job_runs", ["entity_type"], unique=False)
    op.create_index(op.f("ix_job_runs_entity_id"), "job_runs", ["entity_id"], unique=False)
    op.create_index(op.f("ix_job_runs_status"), "job_runs", ["status"], unique=False)
    op.create_index(op.f("ix_job_runs_created_by_user_id"), "job_runs", ["created_by_user_id"], unique=False)

    op.create_table(
        "document_contents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("normalized_text", sa.Text(), nullable=True),
        sa.Column("extraction_status", sa.String(length=30), nullable=False),
        sa.Column("extraction_method", sa.String(length=100), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id"),
    )
    op.create_index(op.f("ix_document_contents_document_id"), "document_contents", ["document_id"], unique=False)

    op.create_table(
        "document_chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.String(length=100), nullable=True),
        sa.Column("chunk_id", sa.String(length=100), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("chunk_text", sa.Text(), nullable=False),
        sa.Column("normalized_text", sa.Text(), nullable=True),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("chunk_id"),
    )
    op.create_index(op.f("ix_document_chunks_document_id"), "document_chunks", ["document_id"], unique=False)
    op.create_index(op.f("ix_document_chunks_user_id"), "document_chunks", ["user_id"], unique=False)

    op.create_table(
        "fine_tune_datasets",
        sa.Column("id", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("template", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "fine_tune_dataset_samples",
        sa.Column("id", sa.String(length=100), nullable=False),
        sa.Column("dataset_id", sa.String(length=100), nullable=False),
        sa.Column("instruction", sa.Text(), nullable=False),
        sa.Column("input", sa.Text(), nullable=False),
        sa.Column("output", sa.Text(), nullable=False),
        sa.Column("source_doc", sa.String(length=500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["dataset_id"], ["fine_tune_datasets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_fine_tune_dataset_samples_dataset_id"),
        "fine_tune_dataset_samples",
        ["dataset_id"],
        unique=False,
    )

    op.create_table(
        "adapter_models",
        sa.Column("id", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("base_model", sa.String(length=255), nullable=False),
        sa.Column("dataset_name", sa.String(length=255), nullable=False),
        sa.Column("lora_rank", sa.Integer(), nullable=False),
        sa.Column("lora_alpha", sa.Integer(), nullable=False),
        sa.Column("training_loss", sa.Float(), nullable=True),
        sa.Column("eval_scores", sa.JSON(), nullable=True),
        sa.Column("adapter_path", sa.String(length=1000), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_adapter_models_name"), "adapter_models", ["name"], unique=False)

    op.create_table(
        "graph_nodes",
        sa.Column("node_id", sa.String(length=255), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("properties", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("node_id"),
    )

    op.create_table(
        "graph_edges",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.String(length=255), nullable=False),
        sa.Column("target_id", sa.String(length=255), nullable=False),
        sa.Column("relationship_type", sa.String(length=100), nullable=False),
        sa.Column("start_date", sa.String(length=50), nullable=True),
        sa.Column("end_date", sa.String(length=50), nullable=True),
        sa.Column("properties", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["graph_nodes.node_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_id"], ["graph_nodes.node_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_graph_edges_source_id"), "graph_edges", ["source_id"], unique=False)
    op.create_index(op.f("ix_graph_edges_target_id"), "graph_edges", ["target_id"], unique=False)

    with op.batch_alter_table("documents", schema=None) as batch_op:
        batch_op.add_column(sa.Column("storage_asset_id", sa.Uuid(), nullable=True))
        batch_op.add_column(sa.Column("processing_job_id", sa.Uuid(), nullable=True))
        batch_op.add_column(sa.Column("content_type", sa.String(length=255), nullable=True))
        batch_op.create_index(batch_op.f("ix_documents_storage_asset_id"), ["storage_asset_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_documents_processing_job_id"), ["processing_job_id"], unique=False)
        batch_op.create_foreign_key("fk_documents_storage_asset_id", "stored_assets", ["storage_asset_id"], ["id"], ondelete="SET NULL")
        batch_op.create_foreign_key("fk_documents_processing_job_id", "job_runs", ["processing_job_id"], ["id"], ondelete="SET NULL")

    with op.batch_alter_table("medical_images", schema=None) as batch_op:
        batch_op.add_column(sa.Column("storage_asset_id", sa.Uuid(), nullable=True))
        batch_op.add_column(sa.Column("thumbnail_asset_id", sa.Uuid(), nullable=True))
        batch_op.add_column(sa.Column("analysis_job_id", sa.Uuid(), nullable=True))
        batch_op.create_index(batch_op.f("ix_medical_images_storage_asset_id"), ["storage_asset_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_medical_images_thumbnail_asset_id"), ["thumbnail_asset_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_medical_images_analysis_job_id"), ["analysis_job_id"], unique=False)
        batch_op.create_foreign_key("fk_medical_images_storage_asset_id", "stored_assets", ["storage_asset_id"], ["id"], ondelete="SET NULL")
        batch_op.create_foreign_key("fk_medical_images_thumbnail_asset_id", "stored_assets", ["thumbnail_asset_id"], ["id"], ondelete="SET NULL")
        batch_op.create_foreign_key("fk_medical_images_analysis_job_id", "job_runs", ["analysis_job_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    with op.batch_alter_table("medical_images", schema=None) as batch_op:
        batch_op.drop_constraint("fk_medical_images_analysis_job_id", type_="foreignkey")
        batch_op.drop_constraint("fk_medical_images_thumbnail_asset_id", type_="foreignkey")
        batch_op.drop_constraint("fk_medical_images_storage_asset_id", type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_medical_images_analysis_job_id"))
        batch_op.drop_index(batch_op.f("ix_medical_images_thumbnail_asset_id"))
        batch_op.drop_index(batch_op.f("ix_medical_images_storage_asset_id"))
        batch_op.drop_column("analysis_job_id")
        batch_op.drop_column("thumbnail_asset_id")
        batch_op.drop_column("storage_asset_id")

    with op.batch_alter_table("documents", schema=None) as batch_op:
        batch_op.drop_constraint("fk_documents_processing_job_id", type_="foreignkey")
        batch_op.drop_constraint("fk_documents_storage_asset_id", type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_documents_processing_job_id"))
        batch_op.drop_index(batch_op.f("ix_documents_storage_asset_id"))
        batch_op.drop_column("content_type")
        batch_op.drop_column("processing_job_id")
        batch_op.drop_column("storage_asset_id")

    op.drop_index(op.f("ix_graph_edges_target_id"), table_name="graph_edges")
    op.drop_index(op.f("ix_graph_edges_source_id"), table_name="graph_edges")
    op.drop_table("graph_edges")
    op.drop_table("graph_nodes")

    op.drop_index(op.f("ix_adapter_models_name"), table_name="adapter_models")
    op.drop_table("adapter_models")

    op.drop_index(op.f("ix_fine_tune_dataset_samples_dataset_id"), table_name="fine_tune_dataset_samples")
    op.drop_table("fine_tune_dataset_samples")
    op.drop_table("fine_tune_datasets")

    op.drop_index(op.f("ix_document_chunks_user_id"), table_name="document_chunks")
    op.drop_index(op.f("ix_document_chunks_document_id"), table_name="document_chunks")
    op.drop_table("document_chunks")

    op.drop_index(op.f("ix_document_contents_document_id"), table_name="document_contents")
    op.drop_table("document_contents")

    op.drop_index(op.f("ix_job_runs_created_by_user_id"), table_name="job_runs")
    op.drop_index(op.f("ix_job_runs_status"), table_name="job_runs")
    op.drop_index(op.f("ix_job_runs_entity_id"), table_name="job_runs")
    op.drop_index(op.f("ix_job_runs_entity_type"), table_name="job_runs")
    op.drop_index(op.f("ix_job_runs_job_type"), table_name="job_runs")
    op.drop_table("job_runs")

    op.drop_index(op.f("ix_stored_assets_checksum"), table_name="stored_assets")
    op.drop_index(op.f("ix_stored_assets_category"), table_name="stored_assets")
    op.drop_index(op.f("ix_stored_assets_owner_user_id"), table_name="stored_assets")
    op.drop_table("stored_assets")
