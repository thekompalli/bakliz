"""init schema

Revision ID: 001_init
Revises:
Create Date: 2026-01-18

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "001_init"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "config",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("industry", sa.Text(), nullable=False, server_default=""),
        sa.Column("location", sa.Text(), nullable=False, server_default=""),
        sa.Column("company_size_min", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("daily_objective", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("email_subject_template", sa.Text(), nullable=False, server_default="Hello {{Company}}"),
        sa.Column(
            "email_body_template",
            sa.Text(),
            nullable=False,
            server_default="Hi {{FirstName}},\n\nI wanted to reach out to {{Company}}.\n",
        ),
        sa.Column("alert_email", sa.Text(), nullable=False, server_default=""),
        sa.Column("run_mode", sa.Enum("live", "dry_run", name="run_mode"), nullable=False, server_default="dry_run"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "blacklist_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "entry_type",
            sa.Enum("company_name", "domain", name="blacklist_entry_type"),
            nullable=False,
        ),
        sa.Column("value_raw", sa.Text(), nullable=False),
        sa.Column("value_norm", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_blacklist_entries_value_norm", "blacklist_entries", ["value_norm"], unique=False)

    op.create_table(
        "history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("date_time", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("company_name", sa.Text(), nullable=True),
        sa.Column("company_domain", sa.Text(), nullable=True),
        sa.Column("employee_count", sa.Integer(), nullable=True),
        sa.Column("first_name", sa.Text(), nullable=True),
        sa.Column("last_name", sa.Text(), nullable=True),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("job_title", sa.Text(), nullable=True),
        sa.Column("status_code", sa.String(length=64), nullable=False),
        sa.Column("status_detail", sa.Text(), nullable=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_domain_norm", sa.Text(), nullable=True),
        sa.Column("company_name_norm", sa.Text(), nullable=True),
        sa.Column("email_norm", sa.Text(), nullable=True),
    )
    op.create_index("ix_history_run_id", "history", ["run_id"], unique=False)
    op.create_index("ix_history_date_time", "history", ["date_time"], unique=False)
    op.create_index("ix_history_company_domain_norm", "history", ["company_domain_norm"], unique=False)
    op.create_index("ix_history_company_name_norm", "history", ["company_name_norm"], unique=False)
    op.create_index("ix_history_email_norm", "history", ["email_norm"], unique=False)

    op.create_table(
        "run_logs",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("quota", sa.Integer(), nullable=False),
        sa.Column("created_drafts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("excluded_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("enrich_failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pool_exhausted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("errors", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("run_mode", sa.String(length=16), nullable=False),
        sa.Column("overrides", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )

    op.create_table(
        "linkup_company_search_cache",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("industry", sa.Text(), nullable=False),
        sa.Column("location", sa.Text(), nullable=False),
        sa.Column("company_size_min", sa.Integer(), nullable=False),
        sa.Column("query_date", sa.Date(), nullable=False),
        sa.Column("response", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("industry", "location", "company_size_min", "query_date", name="uq_company_search_cache"),
    )

    op.create_table(
        "linkup_contacts_cache",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_domain_norm", sa.Text(), nullable=False),
        sa.Column("response", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("company_domain_norm", name="uq_contacts_cache_company"),
    )
    op.create_index("ix_linkup_contacts_cache_company_domain_norm", "linkup_contacts_cache", ["company_domain_norm"])
    op.create_index("ix_linkup_contacts_cache_expires_at", "linkup_contacts_cache", ["expires_at"])

    op.create_table(
        "linkup_email_cache",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("person_key", sa.Text(), nullable=False),
        sa.Column("company_domain_norm", sa.Text(), nullable=False),
        sa.Column("response", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("person_key", "company_domain_norm", name="uq_email_cache_person_company"),
    )
    op.create_index("ix_linkup_email_cache_company_domain_norm", "linkup_email_cache", ["company_domain_norm"])
    op.create_index("ix_linkup_email_cache_expires_at", "linkup_email_cache", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_linkup_email_cache_expires_at", table_name="linkup_email_cache")
    op.drop_index("ix_linkup_email_cache_company_domain_norm", table_name="linkup_email_cache")
    op.drop_table("linkup_email_cache")

    op.drop_index("ix_linkup_contacts_cache_expires_at", table_name="linkup_contacts_cache")
    op.drop_index("ix_linkup_contacts_cache_company_domain_norm", table_name="linkup_contacts_cache")
    op.drop_table("linkup_contacts_cache")

    op.drop_table("linkup_company_search_cache")
    op.drop_table("run_logs")

    op.drop_index("ix_history_email_norm", table_name="history")
    op.drop_index("ix_history_company_name_norm", table_name="history")
    op.drop_index("ix_history_company_domain_norm", table_name="history")
    op.drop_index("ix_history_date_time", table_name="history")
    op.drop_index("ix_history_run_id", table_name="history")
    op.drop_table("history")

    op.drop_index("ix_blacklist_entries_value_norm", table_name="blacklist_entries")
    op.drop_table("blacklist_entries")

    op.drop_table("config")

    op.execute("DROP TYPE IF EXISTS blacklist_entry_type")
    op.execute("DROP TYPE IF EXISTS run_mode")

