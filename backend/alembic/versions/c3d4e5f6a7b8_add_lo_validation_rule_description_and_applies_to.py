"""Add description + applies_to columns to lo_validation_rules_org

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-05-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "lo_validation_rules_org",
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "lo_validation_rules_org",
        sa.Column(
            "applies_to", sa.String(length=255), nullable=False, server_default=""
        ),
    )
    # Drop the server defaults so the application-level default ("") is
    # the only source of truth going forward.
    op.alter_column("lo_validation_rules_org", "description", server_default=None)
    op.alter_column("lo_validation_rules_org", "applies_to", server_default=None)


def downgrade() -> None:
    op.drop_column("lo_validation_rules_org", "applies_to")
    op.drop_column("lo_validation_rules_org", "description")
