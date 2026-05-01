"""AI agent for extracting structured property data from county HTML pages.

Uses call_json_structured() to parse a single county property page into
multiple structured records (deeds, mortgages, liens, tax info, etc.).

Unlike DocumentParserAgent (1:1 raw→parsed), this creates MULTIPLE TADocuments
from a single TARawDocument because a county portal page contains all property data.
"""

import logging
import uuid
from typing import Any

from app.ai.base_service import BaseAIService

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a title search data extraction specialist. You are given the HTML content
of a county property appraiser or recorder website page.

Extract ALL structured property data from this page. The page may contain:
- Property ownership information (current owner, address, parcel, legal description)
- Deed history (warranty deeds, quit-claim deeds, special warranty deeds)
- Mortgage / deed of trust records
- Liens and judgments
- Tax assessment information
- Miscellaneous documents (easements, HOA, plats, etc.)

Extract every record you can find. Be thorough — county pages often contain
tables of recorded documents with dates, book/page numbers, and instrument numbers.

IMPORTANT: The search scope determines what to extract:
- "full": Extract the complete chain of title — all deeds, mortgages, liens, satisfactions
  going back as far as the data shows.
- "current_owner": Extract only the vesting deed (most recent deed to current owner)
  and any current open mortgages/liens. Skip historical chain.
"""

EXTRACTION_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "property_info": {
            "type": "object",
            "properties": {
                "owner_name": {"type": "string"},
                "address": {"type": "string"},
                "municipality": {"type": "string"},
                "zip": {"type": "string"},
                "parcel_number": {"type": "string"},
                "subdivision": {"type": "string"},
                "legal_description": {"type": "string"},
            },
            "required": ["owner_name", "address", "parcel_number"],
        },
        "deeds": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "doc_type": {
                        "type": "string",
                        "enum": ["deed", "assignment"],
                    },
                    "deed_type_detail": {"type": "string"},
                    "recording_date": {"type": "string"},
                    "recording_ref": {"type": "string"},
                    "book_page": {"type": "string"},
                    "instrument_number": {"type": "string"},
                    "grantor": {"type": "string"},
                    "grantee": {"type": "string"},
                    "consideration": {"type": "number"},
                },
                "required": ["doc_type", "grantor", "grantee"],
            },
        },
        "mortgages": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "borrower": {"type": "string"},
                    "lender": {"type": "string"},
                    "trustee": {"type": "string"},
                    "recording_date": {"type": "string"},
                    "recording_ref": {"type": "string"},
                    "book_page": {"type": "string"},
                    "instrument_number": {"type": "string"},
                    "loan_amount": {"type": "number"},
                    "maturity_date": {"type": "string"},
                    "open_closed_end": {"type": "string"},
                    "min_number": {"type": "string"},
                    "riders": {"type": "string"},
                    "associated_docs": {"type": "string"},
                    "comments": {"type": "string"},
                },
                "required": ["borrower", "lender"],
            },
        },
        "liens": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "lien_type": {"type": "string"},
                    "recording_date": {"type": "string"},
                    "recording_ref": {"type": "string"},
                    "book_page": {"type": "string"},
                    "instrument_number": {"type": "string"},
                    "creditor": {"type": "string"},
                    "debtor": {"type": "string"},
                    "amount": {"type": "number"},
                    "status": {"type": "string"},
                },
                "required": ["lien_type", "creditor", "debtor"],
            },
        },
        "tax_info": {
            "type": "object",
            "properties": {
                "parcel_id": {"type": "string"},
                "assessment_year": {"type": "string"},
                "land_value": {"type": "number"},
                "improvement_value": {"type": "number"},
                "total_value": {"type": "number"},
                "tax_amount": {"type": "number"},
                "tax_status": {"type": "string"},
                "homestead_exemption": {"type": "boolean"},
            },
        },
        "misc_documents": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "description": {"type": "string"},
                    "doc_type": {"type": "string"},
                    "recording_date": {"type": "string"},
                    "recording_ref": {"type": "string"},
                    "book_page": {"type": "string"},
                    "instrument_number": {"type": "string"},
                },
                "required": ["description"],
            },
        },
        "confidence": {"type": "number"},
    },
    "required": ["property_info", "deeds", "mortgages", "liens", "confidence"],
}


class PropertyDataExtractorAgent(BaseAIService):
    """Extract structured property data from county portal HTML."""

    def __init__(self, org_id: uuid.UUID):
        from app.config import get_settings
        from app.micro_apps.title_search.ai._model import get_ta_claude_model
        settings = get_settings()
        provider_override = settings.TA_AI_PROVIDER or None
        super().__init__(org_id, provider_override=provider_override)
        ta_model = get_ta_claude_model()
        if ta_model and self._provider == "claude":
            self.model = ta_model

    async def extract_all(
        self,
        raw_content: str,
        search_scope: str = "full",
        property_address: str = "",
    ) -> dict[str, Any]:
        """Extract all property records from county HTML.

        Args:
            raw_content: HTML content from county portal.
            search_scope: "full" or "current_owner".
            property_address: The property address for context.

        Returns:
            Dict with property_info, deeds, mortgages, liens, tax_info,
            misc_documents, and confidence.
        """
        user_message = (
            f"Search scope: {search_scope}\n"
            f"Property address: {property_address}\n\n"
            f"Extract all property data from the following county portal HTML:\n\n"
            f"{raw_content}"
        )

        result = await self.call_json_structured(
            system_prompt=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
            json_schema=EXTRACTION_JSON_SCHEMA,
            max_tokens=8192,
            temperature=0.0,
            timeout=120,
        )

        return result
