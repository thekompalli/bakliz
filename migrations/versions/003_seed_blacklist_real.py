"""seed real blacklist examples

Revision ID: 003_seed_blacklist_real
Revises: 002_seed_demo
Create Date: 2026-01-18

"""

from alembic import op
import sqlalchemy as sa


revision = "003_seed_blacklist_real"
down_revision = "002_seed_demo"
branch_labels = None
depends_on = None


REAL_DOMAIN_ENTRIES = [
    ("microsoft.com", "microsoft.com"),
    ("google.com", "google.com"),
    ("amazon.com", "amazon.com"),
    ("apple.com", "apple.com"),
    ("meta.com", "meta.com"),
    ("openai.com", "openai.com"),
    ("oracle.com", "oracle.com"),
    ("salesforce.com", "salesforce.com"),
    ("sap.com", "sap.com"),
    # France / EU examples
    ("sncf.com", "sncf.com"),
    ("airfrance.com", "airfrance.com"),
    ("orange.com", "orange.com"),
    ("totalenergies.com", "totalenergies.com"),
    ("carrefour.com", "carrefour.com"),
    ("danone.com", "danone.com"),
    ("loreal.com", "loreal.com"),
    ("renaultgroup.com", "renaultgroup.com"),
    ("stellantis.com", "stellantis.com"),
    ("vinci.com", "vinci.com"),
    ("thalesgroup.com", "thalesgroup.com"),
    ("bnpparibas.com", "bnpparibas.com"),
    ("societegenerale.com", "societegenerale.com"),
]


def _insert_if_missing(entry_type: str, value_raw: str, value_norm: str) -> None:
    op.execute(
        sa.text(
            """
            INSERT INTO blacklist_entries (entry_type, value_raw, value_norm)
            SELECT CAST(:entry_type AS blacklist_entry_type), :value_raw, :value_norm
            WHERE NOT EXISTS (
              SELECT 1 FROM blacklist_entries
              WHERE entry_type = CAST(:entry_type AS blacklist_entry_type) AND value_norm = :value_norm
            )
            """
        ).bindparams(entry_type=entry_type, value_raw=value_raw, value_norm=value_norm)
    )


def upgrade() -> None:
    for value_raw, value_norm in REAL_DOMAIN_ENTRIES:
        _insert_if_missing("domain", value_raw, value_norm)


def downgrade() -> None:
    for _raw, norm in REAL_DOMAIN_ENTRIES:
        op.execute(
            sa.text(
                "DELETE FROM blacklist_entries WHERE entry_type = 'domain' AND value_norm = :value_norm"
            ).bindparams(value_norm=norm)
        )
