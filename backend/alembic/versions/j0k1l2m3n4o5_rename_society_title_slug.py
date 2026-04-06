"""Rename Society Title Co to Society Title and update slug

Revision ID: j0k1l2m3n4o5
Revises: i9j0k1l2m3n4
Create Date: 2026-04-06

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "j0k1l2m3n4o5"
down_revision: Union[str, None] = "i9j0k1l2m3n4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "UPDATE organizations SET slug = 'societytitle', name = 'Society Title' "
        "WHERE slug = 'society-title-co'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE organizations SET slug = 'society-title-co', name = 'Society Title Co' "
        "WHERE slug = 'societytitle'"
    )
