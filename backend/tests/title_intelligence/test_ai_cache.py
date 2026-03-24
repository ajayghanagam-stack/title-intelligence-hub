"""Tests for AI output caching in pipeline stages."""

import json
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.micro_apps.title_intelligence.models.extraction import Extraction
from app.micro_apps.title_intelligence.models.flag import Flag
from app.micro_apps.title_intelligence.models.section import Section
from app.micro_apps.title_intelligence.pipeline.version_tracker import (
    compute_ingestion_cache_key,
    compute_ingestion_output_hash,
    compute_risk_cache_key,
)
from app.micro_apps.title_intelligence.pipeline.stages import (
    _replay_ingestion_cache,
    _replay_risk_cache,
    _serialize_ingestion_output,
    _serialize_risk_output,
)

from tests.conftest import TEST_ORG_ID
from tests.title_intelligence.conftest import TEST_PACK_ID


# --- Fixtures ---

SAMPLE_VERSION_INFO = {
    "ai_platform": "anthropic",
    "ai_model": "claude-haiku-4-5-20251001",
    "ingestion_prompt_hash": "abc123" * 10,
    "risk_prompt_hash": "def456" * 10,
    "extraction_tool_hash": "ghi789" * 10,
    "risk_tool_hash": "jkl012" * 10,
    "rules_version": "weighted_5cat_v2",
    "ocr_engine": "tesseract 5.3.0",
    "chunker_version": "hierarchical_v1",
    "pipeline_backend": "background_tasks",
}

SAMPLE_SECTIONS = [
    {"section_type": "schedule_a", "start_page": 1, "end_page": 3, "confidence": 0.95},
    {"section_type": "schedule_b", "start_page": 4, "end_page": 8, "confidence": 0.92},
    {"section_type": "schedule_c", "start_page": 9, "end_page": 12, "confidence": 0.88},
]

SAMPLE_EXTRACTIONS = [
    {
        "extraction_type": "party",
        "label": "Buyer",
        "value": {"name": "John Doe", "role": "buyer"},
        "evidence_refs": [{"page_number": 1, "text_snippet": "Buyer: John Doe"}],
        "section_type": "schedule_a",
        "section_start_page": 1,
        "confidence": 0.95,
    },
    {
        "extraction_type": "property",
        "label": "Property Address",
        "value": {"address": "123 Main St", "city": "Springfield"},
        "evidence_refs": [{"page_number": 2, "text_snippet": "Property: 123 Main St"}],
        "section_type": "schedule_a",
        "section_start_page": 1,
        "confidence": 0.91,
    },
]

SAMPLE_FLAGS = [
    {
        "flag_type": "unresolved_lien",
        "severity": "high",
        "title": "Outstanding Deed of Trust",
        "description": "A deed of trust was found that has not been reconveyed.",
        "ai_explanation": "The deed of trust recorded on 2020-01-15 shows no reconveyance.",
        "evidence_refs": [{"page_number": 5, "text_snippet": "Deed of Trust dated 2020-01-15"}],
        "status": "open",
    },
    {
        "flag_type": "missing_endorsement",
        "severity": "medium",
        "title": "Missing Tax Certificate",
        "description": "Tax certificate not found in commitment.",
        "ai_explanation": "No tax certificate endorsement was detected.",
        "evidence_refs": [{"page_number": 8, "text_snippet": "Tax information"}],
        "status": "open",
    },
]


# --- Cache key determinism tests ---


def test_ingestion_cache_key_deterministic():
    """Same inputs produce the same cache key across repeated calls."""
    file_hash = "a" * 64
    keys = {compute_ingestion_cache_key(file_hash, SAMPLE_VERSION_INFO) for _ in range(10)}
    assert len(keys) == 1


def test_risk_cache_key_deterministic():
    """Same inputs produce the same cache key across repeated calls."""
    ingestion_hash = "b" * 64
    keys = {compute_risk_cache_key(ingestion_hash, SAMPLE_VERSION_INFO) for _ in range(10)}
    assert len(keys) == 1


def test_ingestion_cache_key_changes_on_model_change():
    """Different AI model produces a different cache key."""
    file_hash = "a" * 64
    key1 = compute_ingestion_cache_key(file_hash, SAMPLE_VERSION_INFO)

    modified = {**SAMPLE_VERSION_INFO, "ai_model": "gpt-4o-mini"}
    key2 = compute_ingestion_cache_key(file_hash, modified)
    assert key1 != key2


def test_ingestion_cache_key_changes_on_prompt_change():
    """Different prompt hash produces a different cache key."""
    file_hash = "a" * 64
    key1 = compute_ingestion_cache_key(file_hash, SAMPLE_VERSION_INFO)

    modified = {**SAMPLE_VERSION_INFO, "ingestion_prompt_hash": "zzz999" * 10}
    key2 = compute_ingestion_cache_key(file_hash, modified)
    assert key1 != key2


def test_risk_cache_key_changes_on_ingestion_output():
    """Different ingestion output hash produces a different risk cache key."""
    key1 = compute_risk_cache_key("hash_a" * 10, SAMPLE_VERSION_INFO)
    key2 = compute_risk_cache_key("hash_b" * 10, SAMPLE_VERSION_INFO)
    assert key1 != key2


def test_ingestion_output_hash_order_independent():
    """Shuffled sections/extractions produce the same hash."""
    sections = list(SAMPLE_SECTIONS)
    extractions = list(SAMPLE_EXTRACTIONS)

    hash1 = compute_ingestion_output_hash(sections, extractions)

    # Reverse order
    hash2 = compute_ingestion_output_hash(list(reversed(sections)), list(reversed(extractions)))
    assert hash1 == hash2

    # Shuffle differently
    shuffled_sections = [sections[2], sections[0], sections[1]]
    shuffled_extractions = [extractions[1], extractions[0]]
    hash3 = compute_ingestion_output_hash(shuffled_sections, shuffled_extractions)
    assert hash1 == hash3


# --- Serialization roundtrip tests ---


def test_serialize_deserialize_ingestion_roundtrip():
    """Ingestion serialization roundtrips correctly."""
    cached_data = {"sections": SAMPLE_SECTIONS, "extractions": SAMPLE_EXTRACTIONS}
    serialized = json.dumps(cached_data, sort_keys=True).encode("utf-8")
    deserialized = json.loads(serialized)

    assert len(deserialized["sections"]) == len(SAMPLE_SECTIONS)
    assert len(deserialized["extractions"]) == len(SAMPLE_EXTRACTIONS)
    for i, s in enumerate(deserialized["sections"]):
        assert s["section_type"] == SAMPLE_SECTIONS[i]["section_type"]
        assert s["start_page"] == SAMPLE_SECTIONS[i]["start_page"]
        assert s["end_page"] == SAMPLE_SECTIONS[i]["end_page"]
    for i, e in enumerate(deserialized["extractions"]):
        assert e["extraction_type"] == SAMPLE_EXTRACTIONS[i]["extraction_type"]
        assert e["label"] == SAMPLE_EXTRACTIONS[i]["label"]
        assert e["value"] == SAMPLE_EXTRACTIONS[i]["value"]


def test_serialize_deserialize_risk_roundtrip():
    """Risk serialization roundtrips correctly."""
    serialized = json.dumps(SAMPLE_FLAGS, sort_keys=True).encode("utf-8")
    deserialized = json.loads(serialized)

    assert len(deserialized) == len(SAMPLE_FLAGS)
    for i, f in enumerate(deserialized):
        assert f["flag_type"] == SAMPLE_FLAGS[i]["flag_type"]
        assert f["severity"] == SAMPLE_FLAGS[i]["severity"]
        assert f["title"] == SAMPLE_FLAGS[i]["title"]
        assert f["evidence_refs"] == SAMPLE_FLAGS[i]["evidence_refs"]


# --- DB replay tests ---


@pytest.mark.asyncio
async def test_replay_ingestion_creates_correct_records(db_session: AsyncSession, sample_pack):
    """Replaying cached ingestion data creates the correct DB records."""
    cached_data = {"sections": SAMPLE_SECTIONS, "extractions": SAMPLE_EXTRACTIONS}

    await _replay_ingestion_cache(db_session, TEST_ORG_ID, TEST_PACK_ID, cached_data)
    await db_session.commit()

    # Verify sections
    sec_result = await db_session.execute(
        select(Section).where(Section.pack_id == TEST_PACK_ID, Section.org_id == TEST_ORG_ID)
    )
    sections = list(sec_result.scalars().all())
    assert len(sections) == 3
    section_types = {s.section_type for s in sections}
    assert section_types == {"schedule_a", "schedule_b", "schedule_c"}

    # Verify extractions
    ext_result = await db_session.execute(
        select(Extraction).where(Extraction.pack_id == TEST_PACK_ID, Extraction.org_id == TEST_ORG_ID)
    )
    extractions = list(ext_result.scalars().all())
    assert len(extractions) == 2
    ext_types = {e.extraction_type for e in extractions}
    assert ext_types == {"party", "property"}

    # Verify section FK linking — both extractions reference schedule_a
    schedule_a = next(s for s in sections if s.section_type == "schedule_a")
    for e in extractions:
        assert e.section_id == schedule_a.id


@pytest.mark.asyncio
async def test_replay_risk_creates_correct_records(db_session: AsyncSession, sample_pack):
    """Replaying cached risk data creates the correct DB records."""
    await _replay_risk_cache(db_session, TEST_ORG_ID, TEST_PACK_ID, SAMPLE_FLAGS)
    await db_session.commit()

    result = await db_session.execute(
        select(Flag).where(Flag.pack_id == TEST_PACK_ID, Flag.org_id == TEST_ORG_ID)
    )
    flags = list(result.scalars().all())
    assert len(flags) == 2
    flag_types = {f.flag_type for f in flags}
    assert flag_types == {"unresolved_lien", "missing_endorsement"}
    severities = {f.severity for f in flags}
    assert severities == {"high", "medium"}
    # All flags should have status "open"
    assert all(f.status == "open" for f in flags)
