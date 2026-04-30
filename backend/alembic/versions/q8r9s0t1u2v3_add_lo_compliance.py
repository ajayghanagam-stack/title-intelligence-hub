"""add lo_compliance_runs + loan_context on lo_packages

Revision ID: q8r9s0t1u2v3
Revises: 77eb30ec1c9e
Create Date: 2026-04-28 16:00:00.000000

Adds the persona-aware compliance engine's persistence layer:
  - `lo_packages.loan_context` JSONB — loan scenario captured at upload
  - `lo_compliance_runs` — audit log of every evaluation (rules_version,
    rule_set_hash, loan_context_snapshot, doc_inventory_snapshot, findings,
    summary). Tenant-scoped, FK CASCADE on package delete.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision: str = "q8r9s0t1u2v3"
down_revision: Union[str, None] = "77eb30ec1c9e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Embed loan_context on lo_packages.
    op.add_column(
        "lo_packages",
        sa.Column("loan_context", JSONB(), nullable=True),
    )

    # 2. Compliance run audit table.
    op.create_table(
        "lo_compliance_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "package_id",
            UUID(as_uuid=True),
            sa.ForeignKey("lo_packages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rules_version", sa.String(length=50), nullable=False),
        sa.Column("rule_set_hash", sa.String(length=64), nullable=False),
        sa.Column("loan_context_snapshot", JSONB(), nullable=False),
        sa.Column("doc_inventory_snapshot", JSONB(), nullable=False),
        sa.Column("findings", JSONB(), nullable=False),
        sa.Column("summary", JSONB(), nullable=False),
        sa.Column(
            "org_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organizations.id"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        op.f("ix_lo_compliance_runs_org_id"),
        "lo_compliance_runs",
        ["org_id"],
    )
    op.create_index(
        "ix_lo_compliance_runs_package",
        "lo_compliance_runs",
        ["package_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_lo_compliance_runs_package", table_name="lo_compliance_runs")
    op.drop_index(
        op.f("ix_lo_compliance_runs_org_id"),
        table_name="lo_compliance_runs",
    )
    op.drop_table("lo_compliance_runs")
    op.drop_column("lo_packages", "loan_context")
