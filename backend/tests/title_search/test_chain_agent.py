"""Tests for ChainBuilderAgent (mocked AI calls)."""
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.micro_apps.title_search.ai.chain_builder_agent import ChainBuilderAgent

TEST_ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000010")


@pytest.mark.asyncio
async def test_build_complete_chain():
    """Chain builder returns complete chain."""
    mock_result = {
        "chain_links": [
            {
                "position": 1,
                "link_type": "conveyance",
                "document_id": "doc-1",
                "from_party": {"names": ["Original Owner"]},
                "to_party": {"names": ["Second Owner"]},
                "effective_date": "2010-01-01",
                "is_gap": False,
            },
            {
                "position": 2,
                "link_type": "conveyance",
                "document_id": "doc-2",
                "from_party": {"names": ["Second Owner"]},
                "to_party": {"names": ["Current Owner"]},
                "effective_date": "2020-06-15",
                "is_gap": False,
            },
        ],
        "chain_complete": True,
    }

    with patch.object(ChainBuilderAgent, "call_haiku_structured", new_callable=AsyncMock) as mock_call:
        mock_call.return_value = mock_result
        agent = ChainBuilderAgent.__new__(ChainBuilderAgent)
        agent.org_id = TEST_ORG_ID

        documents = [
            {"id": "doc-1", "doc_type": "deed", "recording_date": "2010-01-01",
             "grantor": {"names": ["Original Owner"]}, "grantee": {"names": ["Second Owner"]}},
            {"id": "doc-2", "doc_type": "deed", "recording_date": "2020-06-15",
             "grantor": {"names": ["Second Owner"]}, "grantee": {"names": ["Current Owner"]}},
        ]
        result = await agent.build(documents)

    assert result["chain_complete"] is True
    assert len(result["chain_links"]) == 2
    assert result["chain_links"][0]["link_type"] == "conveyance"


@pytest.mark.asyncio
async def test_build_chain_with_gap():
    """Chain builder detects a gap."""
    mock_result = {
        "chain_links": [
            {
                "position": 1,
                "link_type": "conveyance",
                "from_party": {"names": ["Owner A"]},
                "to_party": {"names": ["Owner B"]},
                "effective_date": "2000-01-01",
                "is_gap": False,
            },
            {
                "position": 2,
                "link_type": "gap",
                "from_party": {"names": ["Owner B"]},
                "to_party": {"names": ["Owner D"]},
                "effective_date": "2005-01-01",
                "is_gap": True,
                "gap_description": "Missing conveyance from Owner B to Owner C",
            },
        ],
        "chain_complete": False,
    }

    with patch.object(ChainBuilderAgent, "call_haiku_structured", new_callable=AsyncMock) as mock_call:
        mock_call.return_value = mock_result
        agent = ChainBuilderAgent.__new__(ChainBuilderAgent)
        agent.org_id = TEST_ORG_ID

        result = await agent.build([])

    assert result["chain_complete"] is False
    assert any(l["is_gap"] for l in result["chain_links"])
