"""add_eos_fields_to_session_metrics

Revision ID: f8bb5b9e8b83
Revises: b2e5a9c1d4f3
Create Date: 2025-12-21 21:41:04.761565

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f8bb5b9e8b83"
down_revision: str | None = "b2e5a9c1d4f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add EoS fields to session_metrics table
    op.add_column(
        "session_metrics",
        sa.Column("eos_emitted_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "session_metrics",
        sa.Column(
            "eos_signal_type",
            sqlmodel.sql.sqltypes.AutoString(length=64),
            nullable=True,
        ),
    )
    op.add_column(
        "session_metrics",
        sa.Column(
            "eos_reason",
            sqlmodel.sql.sqltypes.AutoString(length=512),
            nullable=True,
        ),
    )
    # Add index on eos_emitted_at for querying ended sessions
    op.create_index(
        "idx_session_metrics_eos_emitted_at",
        "session_metrics",
        ["eos_emitted_at"],
    )


def downgrade() -> None:
    # Drop index first
    op.drop_index("idx_session_metrics_eos_emitted_at", table_name="session_metrics")
    # Drop EoS fields from session_metrics table
    op.drop_column("session_metrics", "eos_reason")
    op.drop_column("session_metrics", "eos_signal_type")
    op.drop_column("session_metrics", "eos_emitted_at")
