"""Tests verifying pipeline cache serialization and flag rules produce valid output."""
import json
import uuid

import pytest

from app.micro_apps.title_search.pipeline.orchestrator import (
    _serialize_parse_output,
    _serialize_chain_output,
)
from app.micro_apps.title_search.ai.document_parser_agent import PARSER_TOOL
from app.micro_apps.title_search.ai.chain_analysis_agent import CHAIN_ANALYSIS_JSON_SCHEMA
from app.micro_apps.title_search.services.flag_rules import VALID_FLAG_TYPES, VALID_SEVERITIES


# ── Serialized output round-trips correctly ──


def test_parse_serialization_contains_all_fields():
    """Parse serialization includes all fields needed for cache replay."""
    class MockDoc:
        def __init__(self, **kw):
            for k, v in kw.items():
                setattr(self, k, v)

    doc = MockDoc(
        doc_type="deed", recording_date="2020-01-15",
        recording_ref="REF-001", grantor={"names": ["A"]},
        grantee={"names": ["B"]}, consideration=250000.0,
        summary="test deed", confidence=0.92, needs_review=False,
        raw_document_id=uuid.uuid4(), doc_metadata=None,
    )
    data = json.loads(_serialize_parse_output([doc]))
    assert len(data) == 1
    # All fields that the cache replay expects must be present
    for key in ["doc_type", "recording_date", "recording_ref", "grantor",
                "grantee", "consideration", "summary", "confidence"]:
        assert key in data[0], f"Missing key: {key}"


def test_chain_serialization_contains_all_fields():
    """Chain serialization includes all fields needed for cache replay."""
    class MockLink:
        def __init__(self, **kw):
            for k, v in kw.items():
                setattr(self, k, v)

    class MockFlag:
        def __init__(self, **kw):
            for k, v in kw.items():
                setattr(self, k, v)

    link = MockLink(
        position=1, link_type="conveyance", document_id=uuid.uuid4(),
        from_party={"names": ["A"]}, to_party={"names": ["B"]},
        effective_date="2020-01-15", is_gap=False, gap_description=None,
    )
    flag = MockFlag(
        flag_type="unreleased_mortgage", severity="high",
        title="Unreleased", description="desc",
        ai_explanation=None, evidence_refs=[],
        document_id=uuid.uuid4(), chain_link_id=None, status="open",
    )
    data = json.loads(_serialize_chain_output([link], [flag]))
    assert "chain_links" in data
    assert "flags" in data
    assert data["flags"][0]["flag_type"] in VALID_FLAG_TYPES
    assert data["flags"][0]["severity"] in VALID_SEVERITIES


# ── Flag rules produce valid types ──


def test_pipeline_flags_use_valid_types():
    """Flags produced by rules engine use valid flag types and severities."""
    from app.micro_apps.title_search.services.flag_rules import detect_all_flags

    # Mock documents that should produce unreleased_mortgage flag
    class MockDoc:
        def __init__(self, **kw):
            for k, v in kw.items():
                setattr(self, k, v)

    docs = [
        MockDoc(id=uuid.uuid4(), doc_type="mortgage", recording_ref="M-001",
                confidence=0.90, recording_date="2020-01-15"),
    ]
    flags = detect_all_flags(docs)
    for f in flags:
        assert f["flag_type"] in VALID_FLAG_TYPES
        assert f["severity"] in VALID_SEVERITIES
        assert "evidence_refs" in f


# ── Chain tool schema compatibility ──


CHAIN_LINK_FIELDS = set(
    CHAIN_ANALYSIS_JSON_SCHEMA["properties"]["chain_links"]["items"]["properties"].keys()
)


def test_chain_link_fields_present():
    """Verify chain analysis JSON schema covers expected chain link fields."""
    expected_fields = {"link_type", "from_party", "to_party", "effective_date", "is_gap"}
    assert expected_fields.issubset(CHAIN_LINK_FIELDS)


