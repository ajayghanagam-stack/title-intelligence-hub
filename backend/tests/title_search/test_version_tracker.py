"""Tests for TSA version tracking and pipeline run creation."""
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import TEST_ORG_ID, TEST_USER_ID, test_session_factory
from tests.title_search.conftest import TEST_ORDER_ID

from app.micro_apps.title_search.models.order import TAOrder
from app.micro_apps.title_search.models.county_source import TACountySource
from app.micro_apps.title_search.models.pipeline_run import TAPipelineRun
from app.micro_apps.title_search.pipeline.orchestrator import run_pipeline
from app.micro_apps.title_search.pipeline.version_tracker import (
    hash_string,
    collect_version_info,
    compute_parse_cache_key,
    compute_parse_output_hash,
    compute_chain_cache_key,
    RULES_VERSION,
)


def test_hash_string_deterministic():
    """Same input always produces the same hash."""
    h1 = hash_string("test input")
    h2 = hash_string("test input")
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex digest


def test_hash_string_different_inputs():
    """Different inputs produce different hashes."""
    h1 = hash_string("input A")
    h2 = hash_string("input B")
    assert h1 != h2


def test_collect_version_info_complete():
    """collect_version_info returns all required keys."""
    from app.config import Settings
    # Reset cache
    import app.micro_apps.title_search.pipeline.version_tracker as vt
    vt._cached_version_info = None
    vt._cached_version_key = None

    settings = Settings(
        DATABASE_URL="sqlite+aiosqlite:///test.db",
        JWT_SECRET="test-secret",
        DEBUG=True,
    )
    info = collect_version_info(settings)

    required_keys = [
        "ai_platform", "ai_model",
        "parser_prompt_hash", "chain_prompt_hash", "anomaly_prompt_hash",
        "parser_tool_hash", "chain_tool_hash", "anomaly_tool_hash",
        "rules_version", "pipeline_backend", "version_metadata",
    ]
    for key in required_keys:
        assert key in info, f"Missing key: {key}"
        assert info[key], f"Empty value for key: {key}"

    assert info["rules_version"] == RULES_VERSION
    assert len(info["parser_prompt_hash"]) == 64
    assert len(info["parser_tool_hash"]) == 64


def test_collect_version_info_cached():
    """Repeated calls return the same object (caching)."""
    from app.config import Settings
    # Reset cache for a clean test
    import app.micro_apps.title_search.pipeline.version_tracker as vt
    vt._cached_version_info = None
    vt._cached_version_key = None

    settings = Settings(
        DATABASE_URL="sqlite+aiosqlite:///test.db",
        JWT_SECRET="test-secret",
        DEBUG=True,
    )
    info1 = collect_version_info(settings)
    info2 = collect_version_info(settings)
    assert info1 is info2  # Same object returned (cached)


def test_parse_cache_key_deterministic():
    """Same inputs produce the same parse cache key."""
    version_info = {
        "ai_model": "gemini/gemini-2.5-flash",
        "parser_prompt_hash": "a" * 64,
        "parser_tool_hash": "b" * 64,
    }
    key1 = compute_parse_cache_key("input_hash_abc", version_info)
    key2 = compute_parse_cache_key("input_hash_abc", version_info)
    assert key1 == key2


def test_parse_cache_key_sensitive_to_model():
    """Changing model produces a different cache key."""
    base = {
        "ai_model": "gemini/gemini-2.5-flash",
        "parser_prompt_hash": "a" * 64,
        "parser_tool_hash": "b" * 64,
    }
    changed = {**base, "ai_model": "gpt-4o-mini"}
    key1 = compute_parse_cache_key("input_hash_abc", base)
    key2 = compute_parse_cache_key("input_hash_abc", changed)
    assert key1 != key2


def test_parse_output_hash_order_independent():
    """Hash is the same regardless of document order."""
    docs = [
        {"doc_type": "deed", "recording_ref": "001"},
        {"doc_type": "mortgage", "recording_ref": "002"},
    ]
    h1 = compute_parse_output_hash(docs)
    h2 = compute_parse_output_hash(list(reversed(docs)))
    assert h1 == h2


def test_chain_cache_key_sensitive_to_rules():
    """Changing rules version produces a different chain cache key."""
    base = {
        "ai_model": "gemini/gemini-2.5-flash",
        "chain_prompt_hash": "c" * 64,
        "chain_tool_hash": "d" * 64,
        "anomaly_prompt_hash": "e" * 64,
        "anomaly_tool_hash": "f" * 64,
        "rules_version": "ta_flag_rules_v1",
    }
    changed = {**base, "rules_version": "ta_flag_rules_v2"}
    key1 = compute_chain_cache_key("parse_hash_xyz", base)
    key2 = compute_chain_cache_key("parse_hash_xyz", changed)
    assert key1 != key2


@pytest_asyncio.fixture
async def pipeline_order_for_version(db_session: AsyncSession, seed_data):
    """Create an order ready for pipeline processing (version tracker test)."""
    cs = TACountySource(
        county="Sangamon",
        state_code="IL",
        source_type="recorder",
        availability="digital",
        is_active=True,
        portal_type="beacon",
        portal_url="https://beacon.schneidercorp.com/Application.aspx?AppID=777",
        search_config={"app_id": "777", "layer_id": "1", "page_id": "1"},
    )
    db_session.add(cs)

    order_id = uuid.uuid4()
    order = TAOrder(
        id=order_id,
        org_id=TEST_ORG_ID,
        created_by=TEST_USER_ID,
        property_address="999 Version St, Springfield, IL",
        county="Sangamon",
        state_code="IL",
        status="processing",
        pipeline_stage="order",
    )
    db_session.add(order)
    await db_session.commit()
    return order_id


@pytest.mark.asyncio
async def test_pipeline_creates_run_record(pipeline_order_for_version):
    """Running the pipeline creates a TAPipelineRun record with version metadata."""
    from unittest.mock import patch, MagicMock, AsyncMock
    from app.micro_apps.title_search.services.county_data_fetcher import FetchResult

    fetch_result = FetchResult(
        content="<html>Version test</html>", content_format="html",
        source_url="https://test.example.com", success=True,
    )
    mock_fetcher_cls = MagicMock()
    mock_fetcher_inst = MagicMock()
    mock_fetcher_inst.fetch = AsyncMock(return_value=fetch_result)
    mock_fetcher_inst.close = AsyncMock()
    mock_fetcher_inst.__aenter__ = AsyncMock(return_value=mock_fetcher_inst)
    mock_fetcher_inst.__aexit__ = AsyncMock(return_value=False)
    mock_fetcher_cls.return_value = mock_fetcher_inst

    mock_extractor_cls = MagicMock()
    mock_extractor_inst = AsyncMock()
    mock_extractor_inst.extract_all = AsyncMock(return_value={
        "property_info": {"owner_name": "V", "address": "V St", "parcel_number": "V-1"},
        "deeds": [{"doc_type": "deed", "recording_date": "2020-01-15",
                    "instrument_number": "V-001", "grantor": "A", "grantee": "B", "consideration": 100000}],
        "mortgages": [], "liens": [], "confidence": 0.90,
    })
    mock_extractor_cls.return_value = mock_extractor_inst

    mock_analysis_cls = MagicMock()
    mock_analysis_inst = AsyncMock()
    mock_analysis_inst.analyze = AsyncMock(return_value={
        "chain_links": [{"position": 1, "link_type": "conveyance", "document_id": None,
                          "from_party": {"names": ["A"]}, "to_party": {"names": ["B"]},
                          "effective_date": "2020-01-15", "is_gap": False}],
        "anomalies": [],
        "chain_complete": True,
    })
    mock_analysis_cls.return_value = mock_analysis_inst

    patchers = [
        patch("app.micro_apps.title_search.services.county_data_fetcher.CountyDataFetcher", mock_fetcher_cls),
        patch("app.micro_apps.title_search.ai.property_data_extractor.PropertyDataExtractorAgent", mock_extractor_cls),
        patch("app.micro_apps.title_search.ai.chain_analysis_agent.ChainAnalysisAgent", mock_analysis_cls),
    ]

    order_id = pipeline_order_for_version
    for p in patchers:
        p.start()
    try:
        await run_pipeline(order_id, TEST_ORG_ID, test_session_factory)
    finally:
        for p in patchers:
            p.stop()

    async with test_session_factory() as db:
        runs = (await db.execute(
            select(TAPipelineRun).where(
                TAPipelineRun.order_id == order_id,
                TAPipelineRun.org_id == TEST_ORG_ID,
            )
        )).scalars().all()

    assert len(runs) == 1
    run = runs[0]
    assert run.ai_platform is not None
    assert run.ai_model is not None
    assert len(run.parser_prompt_hash) == 64
    assert len(run.chain_prompt_hash) == 64
    assert len(run.anomaly_prompt_hash) == 64
    assert len(run.parser_tool_hash) == 64
    assert run.rules_version == RULES_VERSION
    assert run.pipeline_backend is not None
    assert run.status == "completed"
    assert run.completed_at is not None
