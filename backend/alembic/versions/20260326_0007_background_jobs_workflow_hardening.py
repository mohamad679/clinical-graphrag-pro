"""background jobs and workflow hardening

Revision ID: 20260326_0007
Revises: 20260326_0006
Create Date: 2026-03-26 04:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260326_0007"
down_revision: Union[str, None] = "20260326_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("job_runs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("payload_hash", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("idempotency_key", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("max_retries", sa.Integer(), nullable=False, server_default="3"))
        batch_op.add_column(sa.Column("retry_backoff_seconds", sa.Integer(), nullable=False, server_default="30"))
        batch_op.add_column(sa.Column("timeout_seconds", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("last_error", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("worker_task_id", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("dead_lettered_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_index(batch_op.f("ix_job_runs_payload_hash"), ["payload_hash"], unique=False)
        batch_op.create_index(batch_op.f("ix_job_runs_idempotency_key"), ["idempotency_key"], unique=False)

    op.execute("UPDATE job_runs SET max_retries = 3 WHERE max_retries IS NULL")
    op.execute("UPDATE job_runs SET retry_backoff_seconds = 30 WHERE retry_backoff_seconds IS NULL")

    with op.batch_alter_table("workflows", schema=None) as batch_op:
        batch_op.add_column(sa.Column("job_id", sa.Uuid(), nullable=True))
        batch_op.add_column(sa.Column("current_phase", sa.String(length=50), nullable=False, server_default="pending"))
        batch_op.add_column(sa.Column("timeout_seconds", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("metadata", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_index(batch_op.f("ix_workflows_job_id"), ["job_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_workflows_current_phase"), ["current_phase"], unique=False)
        batch_op.create_foreign_key("fk_workflows_job_id", "job_runs", ["job_id"], ["id"], ondelete="SET NULL")

    with op.batch_alter_table("workflow_steps", schema=None) as batch_op:
        batch_op.add_column(sa.Column("phase", sa.String(length=50), nullable=False, server_default="execution"))
        batch_op.add_column(sa.Column("error_message", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("timeout_seconds", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("metadata", sa.JSON(), nullable=True))
        batch_op.create_index(batch_op.f("ix_workflow_steps_phase"), ["phase"], unique=False)

    with op.batch_alter_table("tool_calls", schema=None) as batch_op:
        batch_op.add_column(sa.Column("error_message", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("timeout_seconds", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("metadata", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("tool_calls", schema=None) as batch_op:
        batch_op.drop_column("completed_at")
        batch_op.drop_column("started_at")
        batch_op.drop_column("metadata")
        batch_op.drop_column("timeout_seconds")
        batch_op.drop_column("error_message")

    with op.batch_alter_table("workflow_steps", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_workflow_steps_phase"))
        batch_op.drop_column("metadata")
        batch_op.drop_column("timeout_seconds")
        batch_op.drop_column("error_message")
        batch_op.drop_column("phase")

    with op.batch_alter_table("workflows", schema=None) as batch_op:
        batch_op.drop_constraint("fk_workflows_job_id", type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_workflows_current_phase"))
        batch_op.drop_index(batch_op.f("ix_workflows_job_id"))
        batch_op.drop_column("cancel_requested_at")
        batch_op.drop_column("metadata")
        batch_op.drop_column("timeout_seconds")
        batch_op.drop_column("current_phase")
        batch_op.drop_column("job_id")

    with op.batch_alter_table("job_runs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_job_runs_idempotency_key"))
        batch_op.drop_index(batch_op.f("ix_job_runs_payload_hash"))
        batch_op.drop_column("dead_lettered_at")
        batch_op.drop_column("cancel_requested_at")
        batch_op.drop_column("next_retry_at")
        batch_op.drop_column("dispatched_at")
        batch_op.drop_column("worker_task_id")
        batch_op.drop_column("last_error")
        batch_op.drop_column("timeout_seconds")
        batch_op.drop_column("retry_backoff_seconds")
        batch_op.drop_column("max_retries")
        batch_op.drop_column("idempotency_key")
        batch_op.drop_column("payload_hash")
