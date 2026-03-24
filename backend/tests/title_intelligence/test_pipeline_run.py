import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.micro_apps.title_intelligence.models.pack import Pack
from app.micro_apps.title_intelligence.models.pipeline_run import PipelineRun
from app.micro_apps.title_intelligence.pipeline.version_tracker import (
    hash_string,
    collect_version_info,
)
from tests.conftest import TEST_ORG_ID
from tests.title_intelligence.conftest import TEST_PACK_ID


TEST_PIPELINE_RUN_ID = uuid.UUID("00000000-0000-0000-0000-000000040000")


@pytest_asyncio.fixture
async def sample_pack(db_session: AsyncSession, seed_data):
    """Create a sample pack for pipeline run tests."""
    pack = Pack(
        id=TEST_PACK_ID,
        org_id=TEST_ORG_ID,
        name="Test Title Pack",
        status="processing",
    )
    db_session.add(pack)
    await db_session.commit()
    return pack


@pytest.mark.asyncio
async def test_create_pipeline_run(db_session: AsyncSession, sample_pack):
    """Test creating and retrieving a PipelineRun record."""
    run = PipelineRun(
        id=TEST_PIPELINE_RUN_ID,
        org_id=TEST_ORG_ID,
        pack_id=TEST_PACK_ID,
        input_file_hash="abc123",
        ai_platform="anthropic",
        ai_model="claude-haiku-4-5-20251001",
        ingestion_prompt_hash="hash1",
        risk_prompt_hash="hash2",
        extraction_tool_hash="ext_hash_abc",
        risk_tool_hash="risk_hash_xyz",
        ocr_engine="tesseract 5.3.0",
        chunker_version="hierarchical_v1",
        rules_version="weighted_5cat_v2",
        pipeline_backend="background_tasks",
        version_metadata={"extra": "info"},
        status="running",
    )
    db_session.add(run)
    await db_session.commit()

    result = await db_session.execute(
        select(PipelineRun).where(PipelineRun.id == TEST_PIPELINE_RUN_ID)
    )
    retrieved = result.scalar_one()

    assert retrieved.pack_id == TEST_PACK_ID
    assert retrieved.org_id == TEST_ORG_ID
    assert retrieved.ai_platform == "anthropic"
    assert retrieved.ai_model == "claude-haiku-4-5-20251001"
    assert retrieved.extraction_tool_hash == "ext_hash_abc"
    assert retrieved.risk_tool_hash == "risk_hash_xyz"
    assert retrieved.status == "running"
    assert retrieved.chunker_version == "hierarchical_v1"
    assert retrieved.rules_version == "weighted_5cat_v2"
    assert retrieved.version_metadata == {"extra": "info"}
    assert retrieved.completed_at is None
    assert retrieved.error_message is None


@pytest.mark.asyncio
async def test_pipeline_run_tenant_scoped(db_session: AsyncSession, sample_pack):
    """Test that PipelineRun queries are properly scoped by org_id."""
    run = PipelineRun(
        org_id=TEST_ORG_ID,
        pack_id=TEST_PACK_ID,
        ai_platform="anthropic",
        ai_model="claude-haiku-4-5-20251001",
        ingestion_prompt_hash="hash1",
        risk_prompt_hash="hash2",
        extraction_tool_hash="ext_hash",
        risk_tool_hash="risk_hash",
        ocr_engine="tesseract 5.3.0",
        chunker_version="hierarchical_v1",
        rules_version="weighted_5cat_v2",
        pipeline_backend="background_tasks",
        status="running",
    )
    db_session.add(run)
    await db_session.commit()

    # Query with correct org_id
    result = await db_session.execute(
        select(PipelineRun).where(
            PipelineRun.pack_id == TEST_PACK_ID,
            PipelineRun.org_id == TEST_ORG_ID,
        )
    )
    assert result.scalar_one() is not None

    # Query with wrong org_id returns nothing
    other_org_id = uuid.UUID("00000000-0000-0000-0000-999999999999")
    result = await db_session.execute(
        select(PipelineRun).where(
            PipelineRun.pack_id == TEST_PACK_ID,
            PipelineRun.org_id == other_org_id,
        )
    )
    assert result.scalar_one_or_none() is None


def test_hash_string_deterministic():
    """Test that hash_string produces deterministic output."""
    input_str = "Hello, World!"
    h1 = hash_string(input_str)
    h2 = hash_string(input_str)
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex digest is 64 chars

    # Different input produces different hash
    h3 = hash_string("Different input")
    assert h3 != h1


def test_collect_version_info_returns_required_keys():
    """Test that collect_version_info returns all expected fields."""
    from app.config import Settings

    settings = Settings(
        DATABASE_URL="sqlite+aiosqlite:///./test.db",
        JWT_SECRET="test-secret",
        AI_PLATFORM="anthropic",
        PIPELINE_BACKEND="background_tasks",
        DEBUG=True,
    )
    info = collect_version_info(settings)

    required_keys = {
        "ai_platform",
        "ai_model",
        "ingestion_prompt_hash",
        "risk_prompt_hash",
        "extraction_tool_hash",
        "risk_tool_hash",
        "ocr_engine",
        "chunker_version",
        "rules_version",
        "pipeline_backend",
        "version_metadata",
    }
    assert required_keys.issubset(info.keys())

    assert info["ai_platform"] == "anthropic"
    assert info["ai_model"] == "claude-haiku-4-5-20251001"
    assert info["chunker_version"] == "hierarchical_v1"
    assert info["rules_version"] == "weighted_5cat_v2"
    assert info["pipeline_backend"] == "background_tasks"
    assert len(info["ingestion_prompt_hash"]) == 64
    assert len(info["risk_prompt_hash"]) == 64
    assert len(info["extraction_tool_hash"]) == 64
    assert len(info["risk_tool_hash"]) == 64
