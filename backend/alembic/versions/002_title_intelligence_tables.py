"""Title Intelligence micro app tables

Revision ID: 002
Revises: 001
Create Date: 2026-03-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Packs
    op.create_table(
        "ti_packs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False, index=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default=sa.text("'uploading'")),
        sa.Column("current_stage", sa.String(50), nullable=True),
        sa.Column("readiness_score", sa.Integer, nullable=True),
        sa.Column("readiness_summary", sa.Text, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # Pack Files
    op.create_table(
        "ti_pack_files",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("pack_id", UUID(as_uuid=True), sa.ForeignKey("ti_packs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False, index=True),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("storage_path", sa.Text, nullable=False),
        sa.Column("file_size", sa.BigInteger, nullable=False),
        sa.Column("page_count", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # Pages
    op.create_table(
        "ti_pages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("pack_id", UUID(as_uuid=True), sa.ForeignKey("ti_packs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("file_id", UUID(as_uuid=True), sa.ForeignKey("ti_pack_files.id", ondelete="CASCADE"), nullable=False),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False, index=True),
        sa.Column("page_number", sa.Integer, nullable=False),
        sa.Column("image_uri", sa.Text, nullable=False),
        sa.Column("thumb_uri", sa.Text, nullable=False),
        sa.Column("ocr_uri", sa.Text, nullable=True),
        sa.Column("ocr_text", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # Sections
    op.create_table(
        "ti_sections",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("pack_id", UUID(as_uuid=True), sa.ForeignKey("ti_packs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False, index=True),
        sa.Column("section_type", sa.String(50), nullable=False),
        sa.Column("start_page", sa.Integer, nullable=False),
        sa.Column("end_page", sa.Integer, nullable=False),
        sa.Column("confidence", sa.Float, nullable=False, server_default=sa.text("0.0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # Extractions
    op.create_table(
        "ti_extractions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("pack_id", UUID(as_uuid=True), sa.ForeignKey("ti_packs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False, index=True),
        sa.Column("extraction_type", sa.String(50), nullable=False),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("value", JSONB, nullable=False),
        sa.Column("evidence_refs", JSONB, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("section_id", UUID(as_uuid=True), sa.ForeignKey("ti_sections.id", ondelete="SET NULL"), nullable=True),
        sa.Column("confidence", sa.Float, nullable=False, server_default=sa.text("0.0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # Flags
    op.create_table(
        "ti_flags",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("pack_id", UUID(as_uuid=True), sa.ForeignKey("ti_packs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False, index=True),
        sa.Column("flag_type", sa.String(50), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("ai_explanation", sa.Text, nullable=False),
        sa.Column("evidence_refs", JSONB, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("status", sa.String(50), nullable=False, server_default=sa.text("'open'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # Reviews
    op.create_table(
        "ti_reviews",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("flag_id", UUID(as_uuid=True), sa.ForeignKey("ti_flags.id", ondelete="CASCADE"), nullable=False),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False, index=True),
        sa.Column("reviewer_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("decision", sa.String(50), nullable=False),
        sa.Column("reason_code", sa.String(100), nullable=False, server_default=sa.text("''")),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # Text Chunks
    op.create_table(
        "ti_text_chunks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("pack_id", UUID(as_uuid=True), sa.ForeignKey("ti_packs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False, index=True),
        sa.Column("page_number", sa.Integer, nullable=False),
        sa.Column("section_type", sa.String(50), nullable=True),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # Add tsvector column + GIN index for full-text search
    op.execute("ALTER TABLE ti_text_chunks ADD COLUMN search_vector tsvector")
    op.execute("""
        CREATE INDEX ix_ti_text_chunks_search ON ti_text_chunks USING GIN(search_vector)
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION ti_text_chunks_search_trigger() RETURNS trigger AS $$
        BEGIN
            NEW.search_vector := to_tsvector('english', NEW.content);
            RETURN NEW;
        END
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER ti_text_chunks_search_update BEFORE INSERT OR UPDATE
        ON ti_text_chunks FOR EACH ROW EXECUTE FUNCTION ti_text_chunks_search_trigger()
    """)

    # Chat Messages
    op.create_table(
        "ti_chat_messages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("pack_id", UUID(as_uuid=True), sa.ForeignKey("ti_packs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False, index=True),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("citations", JSONB, nullable=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # Enable RLS on all TI tables
    for table in [
        "ti_packs", "ti_pack_files", "ti_pages", "ti_sections",
        "ti_extractions", "ti_flags", "ti_reviews", "ti_text_chunks",
        "ti_chat_messages",
    ]:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS ti_text_chunks_search_update ON ti_text_chunks")
    op.execute("DROP FUNCTION IF EXISTS ti_text_chunks_search_trigger()")
    op.drop_table("ti_chat_messages")
    op.drop_table("ti_text_chunks")
    op.drop_table("ti_reviews")
    op.drop_table("ti_flags")
    op.drop_table("ti_extractions")
    op.drop_table("ti_sections")
    op.drop_table("ti_pages")
    op.drop_table("ti_pack_files")
    op.drop_table("ti_packs")
