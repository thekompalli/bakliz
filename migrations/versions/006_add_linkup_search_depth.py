"""add linkup_search_depth to config

Revision ID: 006_add_linkup_search_depth
Revises: 005_add_provider_logs
Create Date: 2026-01-28
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "006_add_linkup_search_depth"
down_revision = "005_add_provider_logs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("config", sa.Column("linkup_search_depth", sa.String(length=16), nullable=False, server_default="standard"))
    op.execute("UPDATE config SET linkup_search_depth = 'standard' WHERE linkup_search_depth IS NULL")
    op.alter_column("config", "linkup_search_depth", server_default=None)


def downgrade() -> None:
    op.drop_column("config", "linkup_search_depth")

