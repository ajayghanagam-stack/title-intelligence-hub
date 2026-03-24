"""Tests for AnomalyDetectorAgent (mocked AI calls)."""
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.micro_apps.title_search.ai.anomaly_detector_agent import AnomalyDetectorAgent

TEST_ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000010")


@pytest.mark.asyncio
async def test_detect_anomalies():
    """Detector finds unreleased mortgage and name mismatch."""
    mock_result = {
        "flags": [
            {
                "flag_type": "unreleased_mortgage",
                "severity": "high",
                "title": "Unreleased Mortgage",
                "description": "Mortgage from 2015 has no satisfaction recorded.",
                "document_id": "doc-3",
            },
            {
                "flag_type": "name_mismatch",
                "severity": "medium",
                "title": "Name Mismatch in Chain",
                "description": "Grantee 'John Smith' does not match grantor 'Jon Smith'.",
                "chain_link_id": "link-2",
            },
        ],
    }

    with patch.object(AnomalyDetectorAgent, "call_haiku_structured", new_callable=AsyncMock) as mock_call:
        mock_call.return_value = mock_result
        agent = AnomalyDetectorAgent.__new__(AnomalyDetectorAgent)
        agent.org_id = TEST_ORG_ID

        flags = await agent.detect(
            chain_links=[{"position": 1, "link_type": "conveyance"}],
            documents=[{"id": "doc-1", "doc_type": "deed"}],
        )

    assert len(flags) == 2
    assert flags[0]["flag_type"] == "unreleased_mortgage"
    assert flags[0]["severity"] == "high"
    assert flags[1]["flag_type"] == "name_mismatch"


@pytest.mark.asyncio
async def test_detect_no_anomalies():
    """Clean chain produces no flags."""
    mock_result = {"flags": []}

    with patch.object(AnomalyDetectorAgent, "call_haiku_structured", new_callable=AsyncMock) as mock_call:
        mock_call.return_value = mock_result
        agent = AnomalyDetectorAgent.__new__(AnomalyDetectorAgent)
        agent.org_id = TEST_ORG_ID

        flags = await agent.detect(
            chain_links=[{"position": 1, "link_type": "conveyance"}],
            documents=[{"id": "doc-1", "doc_type": "deed", "confidence": 0.95}],
        )

    assert len(flags) == 0
