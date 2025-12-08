"""Add usage tracking tables

Revision ID: f4083d06c8c1
Revises: 7aeeb5420f00
Create Date: 2025-12-08 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f4083d06c8c1"
down_revision: str | None = "7aeeb5420f00"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Create usage_records table
    op.create_table(
        "usage_records",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column(
            "session_id", sqlmodel.sql.sqltypes.AutoString(length=128), nullable=False
        ),
        sa.Column("turn_number", sa.Integer(), nullable=False),
        sa.Column(
            "backend_type", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False
        ),
        sa.Column(
            "model", sqlmodel.sql.sqltypes.AutoString(length=256), nullable=False
        ),
        sa.Column(
            "frontend_type", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False
        ),
        sa.Column("leg", sqlmodel.sql.sqltypes.AutoString(length=8), nullable=False),
        sa.Column("verbatim_prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("verbatim_completion_tokens", sa.Integer(), nullable=False),
        sa.Column("mutated_prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("mutated_completion_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("backend_reported_usage_json", sa.Text(), nullable=True),
        sa.Column("http_status_code", sa.Integer(), nullable=True),
        sa.Column("tool_call_count", sa.Integer(), nullable=False),
        sa.Column("tool_names_json", sa.Text(), nullable=True),
        sa.Column("ttft_ms", sa.Float(), nullable=True),
        sa.Column("proxy_processing_ms", sa.Float(), nullable=False),
        sa.Column("total_duration_ms", sa.Float(), nullable=False),
        sa.Column(
            "user_agent", sqlmodel.sql.sqltypes.AutoString(length=512), nullable=True
        ),
        sa.Column(
            "app_title", sqlmodel.sql.sqltypes.AutoString(length=256), nullable=True
        ),
        sa.Column(
            "proxy_user", sqlmodel.sql.sqltypes.AutoString(length=256), nullable=True
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create indexes for usage_records
    op.create_index(
        "idx_usage_records_timestamp", "usage_records", ["timestamp"], unique=False
    )
    op.create_index(
        op.f("ix_usage_records_session_id"),
        "usage_records",
        ["session_id"],
        unique=False,
    )
    op.create_index(
        "idx_usage_records_session_timestamp",
        "usage_records",
        ["session_id", "timestamp"],
        unique=False,
    )
    op.create_index(
        op.f("ix_usage_records_backend_type"),
        "usage_records",
        ["backend_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_usage_records_model"), "usage_records", ["model"], unique=False
    )
    op.create_index(
        "idx_usage_records_backend_model",
        "usage_records",
        ["backend_type", "model"],
        unique=False,
    )
    op.create_index(
        "idx_usage_records_backend_model_timestamp",
        "usage_records",
        ["backend_type", "model", "timestamp"],
        unique=False,
    )
    op.create_index(
        op.f("ix_usage_records_total_tokens"),
        "usage_records",
        ["total_tokens"],
        unique=False,
    )
    op.create_index(
        op.f("ix_usage_records_http_status_code"),
        "usage_records",
        ["http_status_code"],
        unique=False,
    )
    op.create_index(
        "idx_usage_records_status_timestamp",
        "usage_records",
        ["http_status_code", "timestamp"],
        unique=False,
    )
    op.create_index(
        op.f("ix_usage_records_proxy_user"),
        "usage_records",
        ["proxy_user"],
        unique=False,
    )
    op.create_index(
        "idx_usage_records_proxy_user_timestamp",
        "usage_records",
        ["proxy_user", "timestamp"],
        unique=False,
    )

    # Create session_metrics table
    op.create_table(
        "session_metrics",
        sa.Column(
            "session_id", sqlmodel.sql.sqltypes.AutoString(length=128), nullable=False
        ),
        sa.Column("start_time", sa.DateTime(), nullable=False),
        sa.Column("last_activity", sa.DateTime(), nullable=False),
        sa.Column("turn_count", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tool_calls", sa.Integer(), nullable=False),
        sa.Column("is_completed", sa.Boolean(), nullable=False),
        sa.Column(
            "backend_type", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=True
        ),
        sa.Column("model", sqlmodel.sql.sqltypes.AutoString(length=256), nullable=True),
        sa.Column(
            "proxy_user", sqlmodel.sql.sqltypes.AutoString(length=256), nullable=True
        ),
        sa.PrimaryKeyConstraint("session_id"),
    )

    # Create indexes for session_metrics
    op.create_index(
        "idx_session_metrics_last_activity",
        "session_metrics",
        ["last_activity"],
        unique=False,
    )
    op.create_index(
        op.f("ix_session_metrics_is_completed"),
        "session_metrics",
        ["is_completed"],
        unique=False,
    )
    op.create_index(
        op.f("ix_session_metrics_proxy_user"),
        "session_metrics",
        ["proxy_user"],
        unique=False,
    )
    op.create_index(
        "idx_session_metrics_user_activity",
        "session_metrics",
        ["proxy_user", "last_activity"],
        unique=False,
    )


def downgrade() -> None:
    # Drop session_metrics indexes
    op.drop_index("idx_session_metrics_user_activity", table_name="session_metrics")
    op.drop_index(op.f("ix_session_metrics_proxy_user"), table_name="session_metrics")
    op.drop_index(op.f("ix_session_metrics_is_completed"), table_name="session_metrics")
    op.drop_index("idx_session_metrics_last_activity", table_name="session_metrics")

    # Drop session_metrics table
    op.drop_table("session_metrics")

    # Drop usage_records indexes
    op.drop_index("idx_usage_records_proxy_user_timestamp", table_name="usage_records")
    op.drop_index(op.f("ix_usage_records_proxy_user"), table_name="usage_records")
    op.drop_index("idx_usage_records_status_timestamp", table_name="usage_records")
    op.drop_index(op.f("ix_usage_records_http_status_code"), table_name="usage_records")
    op.drop_index(op.f("ix_usage_records_total_tokens"), table_name="usage_records")
    op.drop_index(
        "idx_usage_records_backend_model_timestamp", table_name="usage_records"
    )
    op.drop_index("idx_usage_records_backend_model", table_name="usage_records")
    op.drop_index(op.f("ix_usage_records_model"), table_name="usage_records")
    op.drop_index(op.f("ix_usage_records_backend_type"), table_name="usage_records")
    op.drop_index("idx_usage_records_session_timestamp", table_name="usage_records")
    op.drop_index(op.f("ix_usage_records_session_id"), table_name="usage_records")
    op.drop_index("idx_usage_records_timestamp", table_name="usage_records")

    # Drop usage_records table
    op.drop_table("usage_records")
