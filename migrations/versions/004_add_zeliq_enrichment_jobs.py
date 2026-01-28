"""add zeliq enrichment jobs

Revision ID: 004_add_zeliq_enrichment_jobs
Revises: 003_seed_blacklist_real
Create Date: 2026-01-19

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "004_add_zeliq_enrichment_jobs"
down_revision = "003_seed_blacklist_real"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "zeliq_enrichment_jobs",
        sa.Column("job_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("person_key", sa.Text(), nullable=False),
        sa.Column("company_domain_norm", sa.Text(), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "request_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("response_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_zeliq_enrichment_jobs_status", "zeliq_enrichment_jobs", ["status"], unique=False)
    op.create_index("ix_zeliq_enrichment_jobs_person_key", "zeliq_enrichment_jobs", ["person_key"], unique=False)
    op.create_index(
        "ix_zeliq_enrichment_jobs_company_domain_norm", "zeliq_enrichment_jobs", ["company_domain_norm"], unique=False
    )
    op.create_index("ix_zeliq_enrichment_jobs_run_id", "zeliq_enrichment_jobs", ["run_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_zeliq_enrichment_jobs_run_id", table_name="zeliq_enrichment_jobs")
    op.drop_index("ix_zeliq_enrichment_jobs_company_domain_norm", table_name="zeliq_enrichment_jobs")
    op.drop_index("ix_zeliq_enrichment_jobs_person_key", table_name="zeliq_enrichment_jobs")
    op.drop_index("ix_zeliq_enrichment_jobs_status", table_name="zeliq_enrichment_jobs")
    op.drop_table("zeliq_enrichment_jobs")
