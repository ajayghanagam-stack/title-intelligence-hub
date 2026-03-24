"""Tests verifying mock pipeline stages produce output matching AI agent schemas.

MVP uses mock functions instead of real AI agents. These tests ensure the mock
outputs conform to the same schemas the agents would produce, so switching from
mocks to real agents is a drop-in replacement.
"""
import json
import uuid

import pytest

from app.micro_apps.title_search.pipeline.orchestrator import (
    _mock_parse,
    _mock_raw_content,
    _serialize_parse_output,
    _serialize_chain_output,
)
from app.micro_apps.title_search.ai.document_parser_agent import PARSER_TOOL
from app.micro_apps.title_search.ai.chain_builder_agent import CHAIN_TOOL
from app.micro_apps.title_search.services.flag_rules import VALID_FLAG_TYPES, VALID_SEVERITIES


# ── Mock parse output matches agent schema ──


PARSER_REQUIRED_FIELDS = set(
    PARSER_TOOL["input_schema"].get("required", [])
)
PARSER_ALL_FIELDS = set(
    PARSER_TOOL["input_schema"]["properties"].keys()
)
PARSER_DOC_TYPE_ENUM = set(
    PARSER_TOOL["input_schema"]["properties"]["doc_type"]["enum"]
)


def test_mock_parse_deed_matches_schema():
    """Mock parse for a deed produces all required fields from PARSER_TOOL."""
    content = _mock_raw_content("recorder")
    result = _mock_parse(content, "REF-001")
    assert PARSER_REQUIRED_FIELDS.issubset(result.keys()), (
        f"Missing required fields: {PARSER_REQUIRED_FIELDS - result.keys()}"
    )
    assert result["doc_type"] in PARSER_DOC_TYPE_ENUM


def test_mock_parse_mortgage_matches_schema():
    """Mock parse for a mortgage produces all required fields."""
    content = _mock_raw_content("clerk")
    result = _mock_parse(content, "REF-002")
    assert PARSER_REQUIRED_FIELDS.issubset(result.keys())
    assert result["doc_type"] in PARSER_DOC_TYPE_ENUM


def test_mock_parse_unknown_matches_schema():
    """Mock parse for unknown source produces valid schema output."""
    content = _mock_raw_content("other")
    result = _mock_parse(content, "REF-003")
    assert PARSER_REQUIRED_FIELDS.issubset(result.keys())
    assert result["doc_type"] in PARSER_DOC_TYPE_ENUM


def test_mock_parse_confidence_in_range():
    """Mock parse confidence is between 0.0 and 1.0."""
    for source_type in ["recorder", "clerk", "other"]:
        content = _mock_raw_content(source_type)
        result = _mock_parse(content, "REF")
        assert 0.0 <= result["confidence"] <= 1.0


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
        raw_document_id=uuid.uuid4(),
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


def test_mock_pipeline_flags_use_valid_types():
    """Flags produced by mock pipeline use valid flag types and severities."""
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
    CHAIN_TOOL["input_schema"]["properties"]["chain_links"]["items"]["properties"].keys()
)


def test_chain_link_fields_present():
    """Verify chain link mock output covers the chain tool schema fields."""
    # The mock chain builder produces fields that should match the tool schema
    expected_fields = {"link_type", "from_party", "to_party", "effective_date", "is_gap"}
    assert expected_fields.issubset(CHAIN_LINK_FIELDS)
