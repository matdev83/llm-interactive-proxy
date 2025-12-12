"""Add detailed usage tracking columns

Revision ID: b2e5a9c1d4f3
Revises: f4083d06c8c1
Create Date: 2025-12-12 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2e5a9c1d4f3"
down_revision: str | None = "f4083d06c8c1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add backend_instance_id column
    op.add_column(
        "usage_records",
        sa.Column(
            "backend_instance_id",
            sqlmodel.sql.sqltypes.AutoString(length=128),
            nullable=True,
        ),
    )

    # Add native_tool_call_count column
    op.add_column(
        "usage_records",
        sa.Column("native_tool_call_count", sa.Integer(), nullable=False, default=0),
    )

    # Add vtc_tool_call_count column
    op.add_column(
        "usage_records",
        sa.Column("vtc_tool_call_count", sa.Integer(), nullable=False, default=0),
    )

    # Add stream_tps column
    op.add_column(
        "usage_records",
        sa.Column("stream_tps", sa.Float(), nullable=True),
    )

    # Add backend_wait_ms column
    op.add_column(
        "usage_records",
        sa.Column("backend_wait_ms", sa.Float(), nullable=True),
    )

    # Create indexes for backend_instance_id
    op.create_index(
        "idx_usage_records_backend_instance",
        "usage_records",
        ["backend_instance_id"],
        unique=False,
    )
    op.create_index(
        "idx_usage_records_backend_instance_model",
        "usage_records",
        ["backend_instance_id", "model"],
        unique=False,
    )


def downgrade() -> None:
    # Drop indexes
    op.drop_index(
        "idx_usage_records_backend_instance_model", table_name="usage_records"
    )
    op.drop_index("idx_usage_records_backend_instance", table_name="usage_records")

    # Drop columns
    op.drop_column("usage_records", "backend_wait_ms")
    op.drop_column("usage_records", "stream_tps")
    op.drop_column("usage_records", "vtc_tool_call_count")
    op.drop_column("usage_records", "native_tool_call_count")
    op.drop_column("usage_records", "backend_instance_id")
