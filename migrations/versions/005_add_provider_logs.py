"""add provider_logs

Revision ID: 005_add_provider_logs
Revises: 004_add_zeliq_enrichment_jobs
Create Date: 2026-01-27
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "005_add_provider_logs"
down_revision = "004_add_zeliq_enrichment_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "provider_logs",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("key", sa.Text(), nullable=True),
        sa.Column("request", sa.JSON(), nullable=False),
        sa.Column("response", sa.JSON(), nullable=False),
    )
    op.create_index("ix_provider_logs_created_at", "provider_logs", ["created_at"])
    op.create_index("ix_provider_logs_run_id", "provider_logs", ["run_id"])
    op.create_index("ix_provider_logs_provider", "provider_logs", ["provider"])
    op.create_index("ix_provider_logs_kind", "provider_logs", ["kind"])
    op.create_index("ix_provider_logs_key", "provider_logs", ["key"])


def downgrade() -> None:
    op.drop_index("ix_provider_logs_key", table_name="provider_logs")
    op.drop_index("ix_provider_logs_kind", table_name="provider_logs")
    op.drop_index("ix_provider_logs_provider", table_name="provider_logs")
    op.drop_index("ix_provider_logs_run_id", table_name="provider_logs")
    op.drop_index("ix_provider_logs_created_at", table_name="provider_logs")
    op.drop_table("provider_logs")

