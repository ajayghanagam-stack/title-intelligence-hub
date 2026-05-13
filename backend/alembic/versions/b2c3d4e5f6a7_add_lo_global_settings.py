"""Add LO global settings table

Revision ID: b2c3d4e5f6a7
Revises: 6eb14b88b282
Create Date: 2026-05-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import app.models.compat


# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "6eb14b88b282"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "lo_global_settings",
        sa.Column("id", app.models.compat.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", app.models.compat.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "ai_thresholds",
            app.models.compat.JSONB(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "stp_targets",
            app.models.compat.JSONB(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "exception_defaults",
            app.models.compat.JSONB(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "audit",
            app.models.compat.JSONB(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "roles",
            app.models.compat.JSONB(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "notifications",
            app.models.compat.JSONB(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "integrations",
            app.models.compat.JSONB(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "tenant",
            app.models.compat.JSONB(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", name="uq_lo_global_settings_org"),
    )
    op.create_index(
        op.f("ix_lo_global_settings_org_id"),
        "lo_global_settings",
        ["org_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_lo_global_settings_org_id"), table_name="lo_global_settings"
    )
    op.drop_table("lo_global_settings")
