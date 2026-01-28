"""seed demo config

Revision ID: 002_seed_demo
Revises: 001_init
Create Date: 2026-01-18

"""

from alembic import op
import sqlalchemy as sa


revision = "002_seed_demo"
down_revision = "001_init"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            INSERT INTO config
              (id, industry, location, company_size_min, daily_objective,
               email_subject_template, email_body_template, alert_email, run_mode)
            VALUES
              (1, 'Logistics', 'France', 50, 10,
               'Quick question for {{Company}}',
               'Hi {{FirstName}},\\n\\nAre you the right person to discuss fleet/mobility at {{Company}}?\\n\\nBest regards,\\n',
               'alerts@example.com',
               'dry_run'
              )
            ON CONFLICT (id) DO NOTHING
            """
        )
    )

    # Sample blacklist entries (safe defaults)
    op.execute(
        sa.text(
            """
            INSERT INTO blacklist_entries (entry_type, value_raw, value_norm)
            VALUES
              ('domain', 'example.com', 'example.com'),
              ('company_name', 'Acme Corporation', 'acme corporation')
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM blacklist_entries WHERE value_norm IN ('example.com', 'acme corporation')"))
    op.execute(sa.text("DELETE FROM config WHERE id = 1"))

