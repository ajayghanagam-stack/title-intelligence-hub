"""add Phase 2 LO org-config resolver tables

Revision ID: s0t1u2v3w4x5
Revises: r9s0t1u2v3w4
Create Date: 2026-05-09

Phase 2 of the Loan Onboarding refactor — tighten-only profile stacking.
Adds four new tables that form the resolver's three upper layers (Global
+ Loan Program + Investor Overlay) and a FK column on ``lo_packages`` so
each loan picks one program/overlay at upload time.

  - ``lo_doc_type_catalog``         — org's master doc-type list
  - ``lo_extraction_schemas``       — per-doc-type field schema (JSONB)
  - ``lo_validation_rules_org``     — org-level rule library
  - ``lo_program_profiles``         — loan_program + investor_overlay
                                      (overlays carry stacks_with FK)
  - ``lo_packages.program_profile_id`` — selected profile (nullable;
                                          falls back to Global only)

Per-loan tables (``lo_doc_type_configs``, ``lo_validation_rules``)
remain as the lowest-precedence override layer; no schema change there.

Tighten-only invariants are enforced at write time by
``services/tighten_only.py`` (Phase 2), not by the database.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "s0t1u2v3w4x5"
down_revision: Union[str, None] = "r9s0t1u2v3w4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "lo_doc_type_catalog",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False, server_default="other"),
        sa.Column("auto_classify_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("expected_min_pages", sa.Integer(), nullable=True),
        sa.Column("expected_max_pages", sa.Integer(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", "key", name="uq_lo_doc_type_catalog_org_key"),
    )
    op.create_index(
        "ix_lo_doc_type_catalog_org_id", "lo_doc_type_catalog", ["org_id"]
    )

    op.create_table(
        "lo_extraction_schemas",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("doc_type_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("fields", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["doc_type_id"], ["lo_doc_type_catalog.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", "doc_type_id", name="uq_lo_extraction_schemas_org_doc_type"),
    )
    op.create_index(
        "ix_lo_extraction_schemas_org_id", "lo_extraction_schemas", ["org_id"]
    )
    op.create_index(
        "ix_lo_extraction_schemas_doc_type_id", "lo_extraction_schemas", ["doc_type_id"]
    )

    op.create_table(
        "lo_validation_rules_org",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scope", sa.String(length=50), nullable=False),
        sa.Column("rule", sa.String(length=255), nullable=False),
        sa.Column("condition", sa.Text(), nullable=False, server_default=""),
        sa.Column("preset_id", sa.String(length=100), nullable=True),
        sa.Column("severity", sa.String(length=20), nullable=False, server_default="hard"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", "scope", "rule", name="uq_lo_validation_rules_org_scope_rule"),
    )
    op.create_index(
        "ix_lo_validation_rules_org_org_id", "lo_validation_rules_org", ["org_id"]
    )

    op.create_table(
        "lo_program_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("type", sa.String(length=20), nullable=False),
        sa.Column("stacks_with", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("checklist", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("extraction_overrides", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("rule_overrides", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["stacks_with"], ["lo_program_profiles.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_lo_program_profiles_org_id", "lo_program_profiles", ["org_id"]
    )
    op.create_index(
        "ix_lo_program_profiles_stacks_with", "lo_program_profiles", ["stacks_with"]
    )

    op.add_column(
        "lo_packages",
        sa.Column(
            "program_profile_id", postgresql.UUID(as_uuid=True), nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_lo_packages_program_profile_id",
        "lo_packages", "lo_program_profiles",
        ["program_profile_id"], ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_lo_packages_program_profile_id", "lo_packages", ["program_profile_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_lo_packages_program_profile_id", table_name="lo_packages")
    op.drop_constraint("fk_lo_packages_program_profile_id", "lo_packages", type_="foreignkey")
    op.drop_column("lo_packages", "program_profile_id")

    op.drop_index("ix_lo_program_profiles_stacks_with", table_name="lo_program_profiles")
    op.drop_index("ix_lo_program_profiles_org_id", table_name="lo_program_profiles")
    op.drop_table("lo_program_profiles")

    op.drop_index("ix_lo_validation_rules_org_org_id", table_name="lo_validation_rules_org")
    op.drop_table("lo_validation_rules_org")

    op.drop_index("ix_lo_extraction_schemas_doc_type_id", table_name="lo_extraction_schemas")
    op.drop_index("ix_lo_extraction_schemas_org_id", table_name="lo_extraction_schemas")
    op.drop_table("lo_extraction_schemas")

    op.drop_index("ix_lo_doc_type_catalog_org_id", table_name="lo_doc_type_catalog")
    op.drop_table("lo_doc_type_catalog")
