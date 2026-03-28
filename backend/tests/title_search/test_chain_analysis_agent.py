"""Tests for ChainAnalysisAgent (combined chain + anomaly detection)."""
import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.micro_apps.title_search.ai.chain_analysis_agent import (
    ChainAnalysisAgent,
    CHAIN_ANALYSIS_SYSTEM_PROMPT,
    CHAIN_ANALYSIS_JSON_SCHEMA,
)
from tests.conftest import TEST_ORG_ID


SAMPLE_DOCUMENTS = [
    {
        "id": str(uuid.uuid4()),
        "doc_type": "deed",
        "recording_date": "2020-01-15",
        "recording_ref": "2020-001234",
        "grantor": {"names": ["John Smith"]},
        "grantee": {"names": ["Jane Doe"]},
        "consideration": 250000.0,
        "confidence": 0.95,
    },
    {
        "id": str(uuid.uuid4()),
        "doc_type": "mortgage",
        "recording_date": "2020-02-01",
        "recording_ref": "2020-001235",
        "grantor": {"names": ["Jane Doe"]},
        "grantee": {"names": ["First National Bank"]},
        "consideration": 200000.0,
        "confidence": 0.90,
    },
]

MOCK_ANALYSIS_RESULT = {
    "chain_links": [
        {
            "position": 1,
            "link_type": "conveyance",
            "document_id": SAMPLE_DOCUMENTS[0]["id"],
            "from_party": {"names": ["John Smith"]},
            "to_party": {"names": ["Jane Doe"]},
            "effective_date": "2020-01-15",
            "is_gap": False,
        },
        {
            "position": 2,
            "link_type": "encumbrance",
            "document_id": SAMPLE_DOCUMENTS[1]["id"],
            "from_party": {"names": ["Jane Doe"]},
            "to_party": {"names": ["First National Bank"]},
            "effective_date": "2020-02-01",
            "is_gap": False,
        },
    ],
    "anomalies": [
        {
            "flag_type": "unreleased_mortgage",
            "severity": "high",
            "title": "Unreleased Mortgage",
            "description": "Mortgage 2020-001235 has no satisfaction recorded.",
        },
    ],
    "chain_complete": True,
}


def test_json_schema_has_required_fields():
    """JSON schema has chain_links, anomalies, and chain_complete."""
    required = CHAIN_ANALYSIS_JSON_SCHEMA["required"]
    assert "chain_links" in required
    assert "anomalies" in required
    assert "chain_complete" in required


def test_json_schema_chain_link_fields():
    """Chain link items have expected properties."""
    link_props = CHAIN_ANALYSIS_JSON_SCHEMA["properties"]["chain_links"]["items"]["properties"]
    for field in ("position", "link_type", "document_id", "from_party", "to_party", "effective_date", "is_gap"):
        assert field in link_props


def test_json_schema_anomaly_fields():
    """Anomaly items have expected properties."""
    anomaly_props = CHAIN_ANALYSIS_JSON_SCHEMA["properties"]["anomalies"]["items"]["properties"]
    for field in ("flag_type", "severity", "title", "description"):
        assert field in anomaly_props


def test_json_schema_valid_flag_types():
    """Anomaly flag_type enum matches valid flag types."""
    enum = CHAIN_ANALYSIS_JSON_SCHEMA["properties"]["anomalies"]["items"]["properties"]["flag_type"]["enum"]
    expected = [
        "chain_gap", "name_mismatch", "unreleased_mortgage",
        "unsatisfied_lien", "judgment_match", "easement_conflict",
        "missing_source", "low_confidence",
    ]
    assert sorted(enum) == sorted(expected)


def test_system_prompt_covers_both_tasks():
    """System prompt mentions both chain building and anomaly detection."""
    assert "chain of title" in CHAIN_ANALYSIS_SYSTEM_PROMPT.lower()
    assert "anomal" in CHAIN_ANALYSIS_SYSTEM_PROMPT.lower()
    assert "flag_type" in CHAIN_ANALYSIS_SYSTEM_PROMPT


@pytest.mark.asyncio
async def test_analyze_calls_call_json_structured():
    """analyze() calls call_json_structured with correct params."""
    agent = ChainAnalysisAgent.__new__(ChainAnalysisAgent)
    agent.org_id = TEST_ORG_ID

    agent.call_json_structured = AsyncMock(return_value=MOCK_ANALYSIS_RESULT)

    result = await agent.analyze(SAMPLE_DOCUMENTS)

    agent.call_json_structured.assert_called_once()
    call_kwargs = agent.call_json_structured.call_args
    assert call_kwargs.kwargs["temperature"] == 0.0
    assert call_kwargs.kwargs["json_schema"] is CHAIN_ANALYSIS_JSON_SCHEMA
    assert "Documents:" in call_kwargs.kwargs["messages"][0]["content"]

    assert len(result["chain_links"]) == 2
    assert len(result["anomalies"]) == 1
    assert result["chain_complete"] is True


@pytest.mark.asyncio
async def test_analyze_includes_all_document_fields():
    """analyze() formats all document fields in the user message."""
    agent = ChainAnalysisAgent.__new__(ChainAnalysisAgent)
    agent.org_id = TEST_ORG_ID
    agent.call_json_structured = AsyncMock(return_value=MOCK_ANALYSIS_RESULT)

    await agent.analyze(SAMPLE_DOCUMENTS)

    msg = agent.call_json_structured.call_args.kwargs["messages"][0]["content"]
    assert "John Smith" in msg
    assert "2020-01-15" in msg
    assert "250000" in msg
    assert "Confidence" in msg
