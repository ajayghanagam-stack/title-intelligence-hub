"""add loan onboarding tables

Revision ID: k1l2m3n4o5p6
Revises: j0k1l2m3n4o5
Create Date: 2026-04-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


# revision identifiers, used by Alembic.
revision: str = "k1l2m3n4o5p6"
down_revision: Union[str, None] = "j0k1l2m3n4o5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "lo_packages",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("created_by", UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("borrower_name", sa.String(length=500), nullable=True),
        sa.Column("loan_reference", sa.String(length=200), nullable=True),
        sa.Column("hitl_threshold", sa.Float(), nullable=False, server_default="0.75"),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="uploading"),
        sa.Column("pipeline_stage", sa.String(length=50), nullable=True),
        sa.Column("pipeline_error", sa.Text(), nullable=True),
        sa.Column("progress", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_lo_packages_org_id"), "lo_packages", ["org_id"], unique=False)

    op.create_table(
        "lo_package_files",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("package_id", UUID(as_uuid=True), nullable=False),
        sa.Column("filename", sa.String(length=500), nullable=False),
        sa.Column("storage_path", sa.String(length=1000), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("page_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["package_id"], ["lo_packages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_lo_package_files_org_id"), "lo_package_files", ["org_id"], unique=False)
    op.create_index(op.f("ix_lo_package_files_package_id"), "lo_package_files", ["package_id"], unique=False)
    op.create_index(op.f("ix_lo_package_files_content_hash"), "lo_package_files", ["content_hash"], unique=False)

    op.create_table(
        "lo_pages",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("package_id", UUID(as_uuid=True), nullable=False),
        sa.Column("file_id", UUID(as_uuid=True), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("source_page_number", sa.Integer(), nullable=False),
        sa.Column("image_path", sa.String(length=1000), nullable=True),
        sa.Column("thumb_path", sa.String(length=1000), nullable=True),
        sa.Column("heuristic_text", sa.Text(), nullable=True),
        sa.Column("text_length", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["file_id"], ["lo_package_files.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["package_id"], ["lo_packages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_lo_pages_org_id"), "lo_pages", ["org_id"], unique=False)
    op.create_index(op.f("ix_lo_pages_package_id"), "lo_pages", ["package_id"], unique=False)
    op.create_index("ix_lo_pages_package_page", "lo_pages", ["package_id", "page_number"], unique=False)

    op.create_table(
        "lo_doc_type_configs",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("package_id", UUID(as_uuid=True), nullable=False),
        sa.Column("doc_types", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["package_id"], ["lo_packages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("package_id"),
    )
    op.create_index(op.f("ix_lo_doc_type_configs_org_id"), "lo_doc_type_configs", ["org_id"], unique=False)
    op.create_index(op.f("ix_lo_doc_type_configs_package_id"), "lo_doc_type_configs", ["package_id"], unique=False)

    op.create_table(
        "lo_classifications",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("package_id", UUID(as_uuid=True), nullable=False),
        sa.Column("page_id", UUID(as_uuid=True), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("predicted_doc_type", sa.String(length=100), nullable=False),
        sa.Column("predicted_doc_type_alternatives", JSONB(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("page_role", sa.String(length=30), nullable=False, server_default="unknown"),
        sa.Column("detected_fields", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["package_id"], ["lo_packages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["page_id"], ["lo_pages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_lo_classifications_org_id"), "lo_classifications", ["org_id"], unique=False)
    op.create_index(op.f("ix_lo_classifications_package_id"), "lo_classifications", ["package_id"], unique=False)
    op.create_index("ix_lo_classifications_package_page", "lo_classifications", ["package_id", "page_number"], unique=False)

    op.create_table(
        "lo_stacks",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("package_id", UUID(as_uuid=True), nullable=False),
        sa.Column("stack_index", sa.Integer(), nullable=False),
        sa.Column("doc_type", sa.String(length=100), nullable=False),
        sa.Column("page_numbers", JSONB(), nullable=False),
        sa.Column("first_page", sa.Integer(), nullable=False),
        sa.Column("last_page", sa.Integer(), nullable=False),
        sa.Column("classification_confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("overall_confidence", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="pending"),
        sa.Column("requires_hitl", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["package_id"], ["lo_packages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_lo_stacks_org_id"), "lo_stacks", ["org_id"], unique=False)
    op.create_index(op.f("ix_lo_stacks_package_id"), "lo_stacks", ["package_id"], unique=False)
    op.create_index("ix_lo_stacks_package_order", "lo_stacks", ["package_id", "stack_index"], unique=False)

    op.create_table(
        "lo_validation_rules",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("package_id", UUID(as_uuid=True), nullable=False),
        sa.Column("rule_source", sa.String(length=20), nullable=False),
        sa.Column("rule_id", sa.String(length=100), nullable=False),
        sa.Column("config", JSONB(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("doc_type", sa.String(length=100), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["package_id"], ["lo_packages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_lo_validation_rules_org_id"), "lo_validation_rules", ["org_id"], unique=False)
    op.create_index(op.f("ix_lo_validation_rules_package_id"), "lo_validation_rules", ["package_id"], unique=False)

    op.create_table(
        "lo_validation_results",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("package_id", UUID(as_uuid=True), nullable=False),
        sa.Column("stack_id", UUID(as_uuid=True), nullable=False),
        sa.Column("doc_type", sa.String(length=100), nullable=False),
        sa.Column("rules_evaluated", JSONB(), nullable=False),
        sa.Column("confidence_breakdown", JSONB(), nullable=False),
        sa.Column("overall_confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("requires_hitl", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["package_id"], ["lo_packages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["stack_id"], ["lo_stacks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("stack_id"),
    )
    op.create_index(op.f("ix_lo_validation_results_org_id"), "lo_validation_results", ["org_id"], unique=False)
    op.create_index(op.f("ix_lo_validation_results_package_id"), "lo_validation_results", ["package_id"], unique=False)
    op.create_index(op.f("ix_lo_validation_results_stack_id"), "lo_validation_results", ["stack_id"], unique=False)

    op.create_table(
        "lo_hitl_reviews",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("package_id", UUID(as_uuid=True), nullable=False),
        sa.Column("stack_id", UUID(as_uuid=True), nullable=False),
        sa.Column("reviewer_id", UUID(as_uuid=True), nullable=False),
        sa.Column("decision", sa.String(length=20), nullable=False),
        sa.Column("corrected_doc_type", sa.String(length=100), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["package_id"], ["lo_packages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewer_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["stack_id"], ["lo_stacks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_lo_hitl_reviews_org_id"), "lo_hitl_reviews", ["org_id"], unique=False)
    op.create_index(op.f("ix_lo_hitl_reviews_package_id"), "lo_hitl_reviews", ["package_id"], unique=False)
    op.create_index(op.f("ix_lo_hitl_reviews_stack_id"), "lo_hitl_reviews", ["stack_id"], unique=False)

    op.create_table(
        "lo_pipeline_runs",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("package_id", UUID(as_uuid=True), nullable=False),
        sa.Column("input_file_hash", sa.String(length=64), nullable=True),
        sa.Column("ai_platform", sa.String(length=50), nullable=False),
        sa.Column("classifier_model", sa.String(length=100), nullable=False),
        sa.Column("validator_model", sa.String(length=100), nullable=False),
        sa.Column("reasoner_model", sa.String(length=100), nullable=False),
        sa.Column("classify_prompt_hash", sa.String(length=64), nullable=False),
        sa.Column("validate_prompt_hash", sa.String(length=64), nullable=False),
        sa.Column("reason_prompt_hash", sa.String(length=64), nullable=False),
        sa.Column("classify_schema_hash", sa.String(length=64), nullable=False),
        sa.Column("validate_schema_hash", sa.String(length=64), nullable=False),
        sa.Column("rules_version", sa.String(length=50), nullable=False),
        sa.Column("pipeline_backend", sa.String(length=30), nullable=False, server_default="background_tasks"),
        sa.Column("version_metadata", JSONB(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="running"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["package_id"], ["lo_packages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_lo_pipeline_runs_org_id"), "lo_pipeline_runs", ["org_id"], unique=False)
    op.create_index(op.f("ix_lo_pipeline_runs_package_id"), "lo_pipeline_runs", ["package_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_lo_pipeline_runs_package_id"), table_name="lo_pipeline_runs")
    op.drop_index(op.f("ix_lo_pipeline_runs_org_id"), table_name="lo_pipeline_runs")
    op.drop_table("lo_pipeline_runs")

    op.drop_index(op.f("ix_lo_hitl_reviews_stack_id"), table_name="lo_hitl_reviews")
    op.drop_index(op.f("ix_lo_hitl_reviews_package_id"), table_name="lo_hitl_reviews")
    op.drop_index(op.f("ix_lo_hitl_reviews_org_id"), table_name="lo_hitl_reviews")
    op.drop_table("lo_hitl_reviews")

    op.drop_index(op.f("ix_lo_validation_results_stack_id"), table_name="lo_validation_results")
    op.drop_index(op.f("ix_lo_validation_results_package_id"), table_name="lo_validation_results")
    op.drop_index(op.f("ix_lo_validation_results_org_id"), table_name="lo_validation_results")
    op.drop_table("lo_validation_results")

    op.drop_index(op.f("ix_lo_validation_rules_package_id"), table_name="lo_validation_rules")
    op.drop_index(op.f("ix_lo_validation_rules_org_id"), table_name="lo_validation_rules")
    op.drop_table("lo_validation_rules")

    op.drop_index("ix_lo_stacks_package_order", table_name="lo_stacks")
    op.drop_index(op.f("ix_lo_stacks_package_id"), table_name="lo_stacks")
    op.drop_index(op.f("ix_lo_stacks_org_id"), table_name="lo_stacks")
    op.drop_table("lo_stacks")

    op.drop_index("ix_lo_classifications_package_page", table_name="lo_classifications")
    op.drop_index(op.f("ix_lo_classifications_package_id"), table_name="lo_classifications")
    op.drop_index(op.f("ix_lo_classifications_org_id"), table_name="lo_classifications")
    op.drop_table("lo_classifications")

    op.drop_index(op.f("ix_lo_doc_type_configs_package_id"), table_name="lo_doc_type_configs")
    op.drop_index(op.f("ix_lo_doc_type_configs_org_id"), table_name="lo_doc_type_configs")
    op.drop_table("lo_doc_type_configs")

    op.drop_index("ix_lo_pages_package_page", table_name="lo_pages")
    op.drop_index(op.f("ix_lo_pages_package_id"), table_name="lo_pages")
    op.drop_index(op.f("ix_lo_pages_org_id"), table_name="lo_pages")
    op.drop_table("lo_pages")

    op.drop_index(op.f("ix_lo_package_files_content_hash"), table_name="lo_package_files")
    op.drop_index(op.f("ix_lo_package_files_package_id"), table_name="lo_package_files")
    op.drop_index(op.f("ix_lo_package_files_org_id"), table_name="lo_package_files")
    op.drop_table("lo_package_files")

    op.drop_index(op.f("ix_lo_packages_org_id"), table_name="lo_packages")
    op.drop_table("lo_packages")
