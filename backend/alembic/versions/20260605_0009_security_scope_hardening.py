"""security scope hardening

Revision ID: 20260605_0009
Revises: 20260326_0008
Create Date: 2026-06-05 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260605_0009"
down_revision: Union[str, None] = "20260326_0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("tenant_id", sa.String(length=100), nullable=True))
        batch_op.create_index(batch_op.f("ix_users_tenant_id"), ["tenant_id"], unique=False)

    with op.batch_alter_table("medical_images", schema=None) as batch_op:
        batch_op.add_column(sa.Column("tenant_id", sa.String(length=100), nullable=True))
        batch_op.create_index(batch_op.f("ix_medical_images_tenant_id"), ["tenant_id"], unique=False)

    with op.batch_alter_table("evaluation_runs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("tenant_id", sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column("user_id", sa.String(length=100), nullable=True))
        batch_op.create_index(batch_op.f("ix_evaluation_runs_tenant_id"), ["tenant_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_evaluation_runs_user_id"), ["user_id"], unique=False)

    op.execute("UPDATE users SET tenant_id = id WHERE tenant_id IS NULL")
    op.execute("UPDATE medical_images SET tenant_id = user_id WHERE tenant_id IS NULL")


def downgrade() -> None:
    with op.batch_alter_table("evaluation_runs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_evaluation_runs_user_id"))
        batch_op.drop_index(batch_op.f("ix_evaluation_runs_tenant_id"))
        batch_op.drop_column("user_id")
        batch_op.drop_column("tenant_id")

    with op.batch_alter_table("medical_images", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_medical_images_tenant_id"))
        batch_op.drop_column("tenant_id")

    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_users_tenant_id"))
        batch_op.drop_column("tenant_id")
