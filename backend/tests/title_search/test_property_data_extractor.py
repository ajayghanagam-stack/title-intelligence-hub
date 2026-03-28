"""Tests for PropertyDataExtractorAgent."""
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.micro_apps.title_search.ai.property_data_extractor import (
    PropertyDataExtractorAgent,
    EXTRACTION_JSON_SCHEMA,
    SYSTEM_PROMPT,
)


SAMPLE_EXTRACTION = {
    "property_info": {
        "owner_name": "Jane Doe",
        "address": "123 Main St, LaBelle, FL 33935",
        "municipality": "LaBelle",
        "zip": "33935",
        "parcel_number": "1-29-43-01-A",
        "subdivision": "Palm Village",
        "legal_description": "Lot 1, Block 2, Palm Village",
    },
    "deeds": [
        {
            "doc_type": "deed",
            "deed_type_detail": "Warranty Deed",
            "recording_date": "2020-01-15",
            "book_page": "1234/567",
            "instrument_number": "2020001234",
            "grantor": "John Smith",
            "grantee": "Jane Doe",
            "consideration": 250000,
        },
    ],
    "mortgages": [
        {
            "borrower": "Jane Doe",
            "lender": "First National Bank",
            "trustee": "ABC Trust",
            "recording_date": "2020-02-01",
            "book_page": "1234/568",
            "instrument_number": "2020001235",
            "loan_amount": 200000,
            "maturity_date": "2050-02-01",
            "open_closed_end": "Closed",
            "min_number": "100012345678",
            "riders": "PUD",
        },
    ],
    "liens": [],
    "tax_info": {
        "parcel_id": "1-29-43-01-A",
        "assessment_year": "2025",
        "total_value": 225000,
    },
    "misc_documents": [],
    "confidence": 0.92,
}


@pytest.mark.asyncio
async def test_extract_all_full_scope():
    """extract_all returns structured data for full search scope."""
    org_id = uuid.uuid4()

    with patch.object(
        PropertyDataExtractorAgent,
        "call_json_structured",
        new_callable=AsyncMock,
        return_value=SAMPLE_EXTRACTION,
    ):
        agent = PropertyDataExtractorAgent(org_id)
        result = await agent.extract_all(
            raw_content="<html>county data</html>",
            search_scope="full",
            property_address="123 Main St, LaBelle, FL",
        )

    assert result["property_info"]["owner_name"] == "Jane Doe"
    assert len(result["deeds"]) == 1
    assert result["deeds"][0]["grantor"] == "John Smith"
    assert len(result["mortgages"]) == 1
    assert result["mortgages"][0]["trustee"] == "ABC Trust"
    assert result["confidence"] == 0.92


@pytest.mark.asyncio
async def test_extract_all_current_owner_scope():
    """extract_all passes search_scope=current_owner to the AI."""
    org_id = uuid.uuid4()

    current_owner_result = {
        **SAMPLE_EXTRACTION,
        "deeds": [SAMPLE_EXTRACTION["deeds"][0]],  # Only vesting deed
    }

    with patch.object(
        PropertyDataExtractorAgent,
        "call_json_structured",
        new_callable=AsyncMock,
        return_value=current_owner_result,
    ) as mock_call:
        agent = PropertyDataExtractorAgent(org_id)
        result = await agent.extract_all(
            raw_content="<html>county data</html>",
            search_scope="current_owner",
            property_address="123 Main St",
        )

    # Verify scope was passed in the user message
    call_args = mock_call.call_args
    messages = call_args.kwargs.get("messages") or call_args[1] if len(call_args) > 1 else call_args.kwargs["messages"]
    user_msg = messages[0]["content"]
    assert "current_owner" in user_msg

    assert len(result["deeds"]) == 1


@pytest.mark.asyncio
async def test_extract_all_empty_response():
    """extract_all handles empty extraction gracefully."""
    org_id = uuid.uuid4()
    empty_result = {
        "property_info": {"owner_name": "", "address": "", "parcel_number": ""},
        "deeds": [],
        "mortgages": [],
        "liens": [],
        "confidence": 0.3,
    }

    with patch.object(
        PropertyDataExtractorAgent,
        "call_json_structured",
        new_callable=AsyncMock,
        return_value=empty_result,
    ):
        agent = PropertyDataExtractorAgent(org_id)
        result = await agent.extract_all(
            raw_content="<html>empty page</html>",
        )

    assert result["confidence"] == 0.3
    assert len(result["deeds"]) == 0
    assert len(result["mortgages"]) == 0


def test_json_schema_structure():
    """Verify the JSON schema has required top-level fields."""
    assert "property_info" in EXTRACTION_JSON_SCHEMA["properties"]
    assert "deeds" in EXTRACTION_JSON_SCHEMA["properties"]
    assert "mortgages" in EXTRACTION_JSON_SCHEMA["properties"]
    assert "liens" in EXTRACTION_JSON_SCHEMA["properties"]
    assert "confidence" in EXTRACTION_JSON_SCHEMA["properties"]


def test_system_prompt_mentions_scope():
    """System prompt should mention search scope for the AI."""
    assert "full" in SYSTEM_PROMPT.lower()
    assert "current_owner" in SYSTEM_PROMPT.lower()
