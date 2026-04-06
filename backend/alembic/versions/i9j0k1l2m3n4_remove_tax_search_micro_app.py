"""remove tax search micro app

Revision ID: i9j0k1l2m3n4
Revises: h8i9j0k1l2m3
Create Date: 2026-04-06
"""
from typing import Union

from alembic import op
import sqlalchemy as sa

revision: str = "i9j0k1l2m3n4"
down_revision: Union[str, None] = "h8i9j0k1l2m3"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    # Delete any subscriptions referencing the tax-search app, then delete the app
    op.execute("""
        DELETE FROM subscriptions
        WHERE app_id IN (SELECT id FROM micro_apps WHERE slug = 'tax-search')
    """)
    op.execute("DELETE FROM micro_apps WHERE slug = 'tax-search'")


def downgrade() -> None:
    op.execute("""
        INSERT INTO micro_apps (name, slug, description, icon) VALUES
            ('Tax Search & Certification', 'tax-search', 'Automated tax search and certification', 'receipt-text')
    """)
