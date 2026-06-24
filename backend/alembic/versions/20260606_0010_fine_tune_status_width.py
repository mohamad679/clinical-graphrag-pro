"""fine tune explicit status width

Revision ID: 20260606_0010
Revises: 20260605_0009
Create Date: 2026-06-06 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260606_0010"
down_revision: Union[str, None] = "20260605_0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("job_runs", schema=None) as batch_op:
        batch_op.alter_column(
            "status",
            existing_type=sa.String(length=20),
            type_=sa.String(length=50),
            existing_nullable=False,
            existing_server_default=None,
        )


def downgrade() -> None:
    with op.batch_alter_table("job_runs", schema=None) as batch_op:
        batch_op.alter_column(
            "status",
            existing_type=sa.String(length=50),
            type_=sa.String(length=20),
            existing_nullable=False,
            existing_server_default=None,
        )
