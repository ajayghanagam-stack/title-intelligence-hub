"""Update default hitl_threshold on lo_packages from 0.75 to 0.96

Revision ID: l2m3n4o5p6q7
Revises: k1l2m3n4o5p6
Create Date: 2026-04-23

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "l2m3n4o5p6q7"
down_revision: Union[str, None] = "k1l2m3n4o5p6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "lo_packages",
        "hitl_threshold",
        server_default="0.96",
    )


def downgrade() -> None:
    op.alter_column(
        "lo_packages",
        "hitl_threshold",
        server_default="0.75",
    )
