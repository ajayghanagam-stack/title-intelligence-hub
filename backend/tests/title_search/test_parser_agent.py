"""Tests for DocumentParserAgent (mocked AI calls)."""
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.micro_apps.title_search.ai.document_parser_agent import DocumentParserAgent

TEST_ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000010")


@pytest.mark.asyncio
async def test_parse_high_confidence():
    """Parser returns high confidence → needs_review=False."""
    mock_result = {
        "doc_type": "deed",
        "recording_date": "2020-01-15",
        "recording_ref": "2020-001234",
        "grantor": {"names": ["John Smith"], "entity_type": "individual"},
        "grantee": {"names": ["Jane Doe"], "entity_type": "individual"},
        "consideration": 250000,
        "summary": "Warranty deed transferring property",
        "confidence": 0.95,
    }

    with patch.object(DocumentParserAgent, "call_haiku_structured", new_callable=AsyncMock) as mock_call:
        mock_call.return_value = mock_result
        agent = DocumentParserAgent.__new__(DocumentParserAgent)
        agent.org_id = TEST_ORG_ID

        result = await agent.parse("Raw document text here")

    assert result["doc_type"] == "deed"
    assert result["confidence"] == 0.95
    assert result["needs_review"] is False


@pytest.mark.asyncio
async def test_parse_low_confidence():
    """Parser returns low confidence → needs_review=True."""
    mock_result = {
        "doc_type": "other",
        "confidence": 0.45,
    }

    with patch.object(DocumentParserAgent, "call_haiku_structured", new_callable=AsyncMock) as mock_call:
        mock_call.return_value = mock_result
        agent = DocumentParserAgent.__new__(DocumentParserAgent)
        agent.org_id = TEST_ORG_ID

        result = await agent.parse("Unclear document text")

    assert result["needs_review"] is True
    assert result["confidence"] < 0.70
