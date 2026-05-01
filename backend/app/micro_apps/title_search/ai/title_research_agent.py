"""Title Research Agent using Claude web search.

Replaces portal scraping with autonomous web research. Claude searches
county property appraiser, clerk of court, and other public record sources
to gather comprehensive 22-entity property data.
"""

import hashlib
import json
import logging
import uuid
from typing import Any

from app.ai.base_service import BaseAIService

logger = logging.getLogger(__name__)

RESEARCH_SYSTEM_PROMPT = """\
Act as an expert US title searcher. Look up all relevant online records and \
do a full title search for the subject property. Produce a COMPLETE \
professional title search report covering all 10 standard sections.

Search the county property appraiser, county clerk official records, tax \
collector, court records, and any other relevant public sources. Use your \
professional knowledge of real estate title practices, county office \
resources, typical subdivision development patterns, and state-specific \
title law to fill in every section completely.

## IMPORTANT: No empty fields

Every field must have meaningful content. Never return null, empty strings, \
or empty arrays. For any data you cannot find via web search:
- Provide your best professional assessment or estimate based on comparable \
data, property characteristics, and county norms.
- Include specific verification instructions with actual county office URLs, \
phone numbers, and addresses where the reader can confirm the data.
- For dollar amounts, provide estimated ranges based on comparable sales and \
local tax rates (e.g., "Approx. $3,000-$5,000 annually").

## What to include

- **Property ID**: address, parcel number, legal description, property type, \
year built, bedrooms/bathrooms, square footage, zoning, flood zone.
- **Ownership**: current owner(s), vesting type, deed reference, homestead \
exemption status, mailing address, occupancy status.
- **Chain of title**: Reconstruct at least 3-4 links (original plat, \
builder deed, any resales, current owner) using available data and standard \
subdivision development patterns.
- **Mortgages & liens**: Include purchase money mortgage with verification \
note. Cover all 10 lien categories with specific verification resources.
- **Tax status**: tax year, assessed/market value, annual tax estimate, \
payment status, millage rate, tax collector URL.
- **Easements & restrictions**: subdivision plat, utility/drainage easements, \
HOA/CC&Rs, access, private restrictions, survey recommendation.
- **Court proceedings**: One entry per category (foreclosure, lis pendens, \
bankruptcy, probate, divorce) with verification instructions and court URLs.
- **Title opinion**: At least 8 professional items covering property ID, \
ownership, liens, taxes, survey, foreclosure, bankruptcy, HOA, and title \
insurance recommendation. Mark each as open or resolved.
- **Next steps**: At least 8 detailed action items with specific URLs.
- **Key contacts**: At least 6 contacts (property appraiser, clerk, tax \
collector, code enforcement, utility company, bankruptcy court) with \
addresses, phones, and websites.
- **Comparable sales**: At least 2-3 nearby recent sales.

Call submit_research_results with your complete structured findings.
"""

RESEARCH_RESULT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "property_identification": {
            "type": "object",
            "description": "Core property identifiers — ALL fields required, use verification text if not found",
            "properties": {
                "parcel_number": {"type": "string", "description": "Parcel RE# or verification instruction"},
                "alternate_parcel_id": {"type": "string"},
                "property_address": {"type": "string"},
                "city": {"type": "string"},
                "state": {"type": "string"},
                "zip_code": {"type": "string"},
                "county": {"type": "string"},
                "legal_description": {"type": "string", "description": "Legal description or where to obtain it"},
                "subdivision": {"type": "string"},
                "section_township_range": {"type": "string"},
            },
        },
        "physical_attributes": {
            "type": "object",
            "description": "Physical property details — provide found data or estimates",
            "properties": {
                "property_type": {"type": "string", "description": "e.g., Single Family Residence (SFR)"},
                "year_built": {"type": ["integer", "null"]},
                "living_area_sqft": {"type": ["number", "null"]},
                "total_area_sqft": {"type": ["number", "null"]},
                "bedrooms": {"type": ["integer", "null"]},
                "bathrooms": {"type": ["number", "null"]},
                "stories": {"type": ["number", "null"]},
                "garage": {"type": "string"},
                "pool": {"type": ["boolean", "null"]},
                "construction_type": {"type": "string"},
                "roof_type": {"type": "string"},
            },
        },
        "lot_and_land": {
            "type": "object",
            "description": "Lot dimensions, zoning, flood zone — provide data or verification guidance",
            "properties": {
                "lot_size_acres": {"type": ["number", "null"]},
                "lot_size_sqft": {"type": ["number", "null"]},
                "lot_dimensions": {"type": "string"},
                "zoning": {"type": "string", "description": "Zoning code or 'Residential' with verification note"},
                "zoning_description": {"type": "string"},
                "flood_zone": {"type": "string", "description": "FEMA zone or 'Recommend FEMA FIRM map verification'"},
                "flood_zone_description": {"type": "string"},
                "land_use_code": {"type": "string"},
            },
        },
        "hoa": {
            "type": "object",
            "description": "HOA / subdivision association info",
            "properties": {
                "has_hoa": {"type": ["boolean", "null"]},
                "hoa_name": {"type": "string"},
                "hoa_contact": {"type": "string"},
                "hoa_fees": {"type": "string"},
                "hoa_violations": {"type": "array", "items": {"type": "string"}, "default": []},
            },
        },
        "location_context": {
            "type": "object",
            "description": "Neighborhood and location context",
            "properties": {
                "school_district": {"type": "string"},
                "census_tract": {"type": "string"},
                "neighborhood": {"type": "string"},
                "municipality": {"type": "string"},
            },
        },
        "current_ownership": {
            "type": "object",
            "description": "Current owner details — provide found data or verification guidance for every field",
            "properties": {
                "owner_names": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                "ownership_type": {"type": "string", "description": "e.g., Fee Simple (presumed for residential SFR)"},
                "vesting_deed_ref": {"type": "string", "description": "Recording reference or where to find it"},
                "vesting_deed_date": {"type": "string"},
                "vesting_deed_type": {"type": "string", "description": "Warranty, special warranty, quit claim, etc."},
                "mailing_address": {"type": "string"},
                "homestead_exemption": {"type": "string", "description": "Yes/No/Status unknown with verification note"},
                "occupancy_status": {"type": "string", "description": "e.g., 2 residents on record per public directory data"},
            },
        },
        "chain_of_title": {
            "type": "array",
            "description": "Reconstructed conveyance history — MUST have at least 3-4 links",
            "items": {
                "type": "object",
                "properties": {
                    "deed_type": {"type": "string"},
                    "grantor": {"type": "string"},
                    "grantee": {"type": "string"},
                    "recording_date": {"type": "string"},
                    "recording_ref": {"type": "string", "description": "Book/page, instrument number, or 'TBD'"},
                    "consideration": {"type": "string"},
                    "notes": {"type": "string"},
                },
            },
            "minItems": 3,
        },
        "mortgages": {
            "type": "array",
            "description": "Mortgages — include at least purchase money mortgage with verification note",
            "items": {
                "type": "object",
                "properties": {
                    "lender": {"type": "string"},
                    "borrower": {"type": "string"},
                    "amount": {"type": "string"},
                    "recording_date": {"type": "string"},
                    "recording_ref": {"type": "string"},
                    "maturity_date": {"type": "string"},
                    "status": {"type": "string", "description": "active, satisfied, released, or verify"},
                    "satisfaction_ref": {"type": "string"},
                    "notes": {"type": "string"},
                },
            },
            "minItems": 1,
        },
        "liens": {
            "type": "array",
            "description": "Liens/judgments — include entries for each lien category with verification guidance",
            "items": {
                "type": "object",
                "properties": {
                    "lien_type": {"type": "string", "description": "federal_tax, state_tax, judgment, hoa, mechanic, utility, code_enforcement, child_support"},
                    "creditor": {"type": "string"},
                    "debtor": {"type": "string"},
                    "amount": {"type": "string"},
                    "recording_date": {"type": "string"},
                    "recording_ref": {"type": "string"},
                    "status": {"type": "string", "description": "not_identified, active, released, or verify"},
                    "notes": {"type": "string", "description": "Verification instruction with specific URL/office"},
                },
            },
            "minItems": 1,
        },
        "tax_status": {
            "type": "object",
            "description": "Property tax information — provide data or estimates with verification",
            "properties": {
                "tax_year": {"type": "string", "description": "e.g., 2025 tax roll (certified October 2025)"},
                "assessed_value": {"type": "string", "description": "Dollar amount or estimate range with source"},
                "land_value": {"type": "string"},
                "improvement_value": {"type": "string"},
                "total_tax_amount": {"type": "string", "description": "Dollar amount or 'Approx. $X-$Y annually'"},
                "tax_status": {"type": "string", "description": "VERIFY with specific tax collector URL"},
                "delinquent_amount": {"type": "string"},
                "exemptions": {"type": "array", "items": {"type": "string"}},
                "special_assessments": {"type": "array", "items": {"type": "string"}},
                "millage_rate": {"type": "string", "description": "e.g., Approx. 18-20 mills total"},
                "tax_collector_url": {"type": "string"},
            },
        },
        "easements": {
            "type": "array",
            "description": "Easements — MUST include at least: subdivision plat, utility, drainage entries",
            "items": {
                "type": "object",
                "properties": {
                    "easement_type": {"type": "string"},
                    "beneficiary": {"type": "string"},
                    "recording_ref": {"type": "string"},
                    "description": {"type": "string"},
                },
            },
            "minItems": 3,
        },
        "ccrs_restrictions": {
            "type": "object",
            "description": "CC&Rs and deed restrictions",
            "properties": {
                "has_ccrs": {"type": ["boolean", "null"]},
                "recording_ref": {"type": "string"},
                "key_restrictions": {"type": "array", "items": {"type": "string"}},
                "notes": {"type": "string"},
                "access_ingress_egress": {"type": "string", "description": "Street/road access description"},
                "private_restrictions": {"type": "string"},
            },
        },
        "notice_of_commencement": {
            "type": "object",
            "description": "NOC filings (construction/renovation)",
            "properties": {
                "has_noc": {"type": ["boolean", "null"]},
                "recording_ref": {"type": "string"},
                "recording_date": {"type": "string"},
                "contractor": {"type": "string"},
                "description": {"type": "string"},
                "final_payment_affidavit": {"type": ["boolean", "null"]},
            },
        },
        "court_proceedings": {
            "type": "array",
            "description": "Court proceedings — MUST have 6 entries, one per category, with verification URLs",
            "items": {
                "type": "object",
                "properties": {
                    "case_type": {"type": "string", "description": "foreclosure, foreclosure_sale, lis_pendens, bankruptcy, probate, divorce"},
                    "case_number": {"type": "string"},
                    "parties": {"type": "string"},
                    "filing_date": {"type": "string"},
                    "status": {"type": "string", "description": "not_identified, active, pending, etc."},
                    "notes": {"type": "string", "description": "Verification instruction with specific court/registry URL"},
                },
            },
            "minItems": 6,
        },
        "permits": {
            "type": "array",
            "description": "Building permits and code enforcement",
            "items": {
                "type": "object",
                "properties": {
                    "permit_type": {"type": "string"},
                    "permit_number": {"type": "string"},
                    "issue_date": {"type": "string"},
                    "status": {"type": "string", "description": "open, closed, violation"},
                    "description": {"type": "string"},
                    "violation_details": {"type": "string"},
                },
            },
            "default": [],
        },
        "survey_plat": {
            "type": "object",
            "description": "Survey and plat information",
            "properties": {
                "has_survey": {"type": ["boolean", "null"]},
                "survey_date": {"type": "string"},
                "surveyor": {"type": "string"},
                "plat_book_page": {"type": "string", "description": "Plat book/page or 'Obtain from County Clerk'"},
                "notes": {"type": "string"},
                "recommendation": {"type": "string", "description": "e.g., ALTA/NSPS survey strongly recommended"},
            },
        },
        "title_opinion_items": {
            "type": "array",
            "description": "Professional title opinion items — MUST have at least 8 items covering all standard categories",
            "items": {
                "type": "object",
                "properties": {
                    "item": {"type": "string", "description": "Short title (e.g., Property Identified, Ownership Verification Pending)"},
                    "severity": {"type": "string", "description": "critical, high, medium, low"},
                    "status": {"type": "string", "description": "open or resolved"},
                    "recommendation": {"type": "string", "description": "Detailed recommendation with specific action"},
                },
            },
            "minItems": 8,
        },
        "next_steps": {
            "type": "array",
            "description": "Detailed action items — MUST have at least 8 steps with specific URLs and instructions",
            "items": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "description": "Specific action with URL/office name (e.g., 'Access Duval County Property Appraiser (paopropertysearch.coj.net) — enter address to confirm parcel RE#')"},
                    "priority": {"type": "string", "description": "high, medium, low"},
                    "assigned_to": {"type": "string"},
                    "notes": {"type": "string"},
                },
            },
            "minItems": 8,
        },
        "key_contacts": {
            "type": "array",
            "description": "County/state contacts — MUST have at least 6 including property appraiser, clerk, tax collector, code enforcement, utility, bankruptcy court",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "role": {"type": "string"},
                    "phone": {"type": "string"},
                    "address": {"type": "string"},
                    "website": {"type": "string"},
                },
            },
            "minItems": 6,
        },
        "comparable_sales": {
            "type": "array",
            "description": "Recent comparable property sales nearby — find at least 2-3",
            "items": {
                "type": "object",
                "properties": {
                    "address": {"type": "string"},
                    "sale_date": {"type": "string"},
                    "sale_price": {"type": "string"},
                    "sqft": {"type": ["number", "null"]},
                    "notes": {"type": "string"},
                },
            },
        },
        "search_summary": {
            "type": "object",
            "description": "Summary of the research process",
            "properties": {
                "sources_searched": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                "sources_unavailable": {"type": "array", "items": {"type": "string"}},
                "confidence_level": {"type": "string", "description": "high, medium, low"},
                "notes": {"type": "string"},
                "search_date": {"type": "string"},
            },
        },
    },
    "required": [
        "property_identification", "physical_attributes", "lot_and_land",
        "current_ownership", "chain_of_title", "mortgages", "liens",
        "tax_status", "easements", "ccrs_restrictions", "court_proceedings",
        "title_opinion_items", "next_steps", "key_contacts",
        "comparable_sales", "search_summary",
    ],
}

# Hash of the schema for cache key computation
RESEARCH_SCHEMA_HASH = hashlib.sha256(
    json.dumps(RESEARCH_RESULT_SCHEMA, sort_keys=True).encode()
).hexdigest()

RESEARCH_PROMPT_HASH = hashlib.sha256(
    RESEARCH_SYSTEM_PROMPT.encode()
).hexdigest()


class TitleResearchAgent(BaseAIService):
    """Autonomous title researcher using Claude web search."""

    def __init__(self, org_id: uuid.UUID):
        from app.config import get_settings
        settings = get_settings()
        provider_override = settings.TA_AI_PROVIDER or None
        super().__init__(org_id, role="title_researcher", provider_override=provider_override)

    async def research(
        self,
        property_address: str,
        county: str,
        state_code: str,
        owner_name: str | None = None,
        parcel_number: str | None = None,
        search_scope: str = "full",
        search_years: int = 60,
    ) -> tuple[dict[str, Any], list[dict[str, str]]]:
        """Conduct comprehensive title research via web search.

        Args:
            property_address: Full street address.
            county: County name.
            state_code: Two-letter state code.
            owner_name: Known owner name (optional).
            parcel_number: Known parcel number (optional).
            search_scope: "full" or "current_owner".
            search_years: Number of years to search back.

        Returns:
            (research_data, citations) — structured 22-entity dict + source URLs.
        """
        # Build research prompt with property context
        context_parts = [
            f"Property Address: {property_address}",
            f"County: {county} County",
            f"State: {state_code}",
        ]
        if owner_name:
            context_parts.append(f"Known Owner: {owner_name}")
        if parcel_number:
            context_parts.append(f"Parcel Number: {parcel_number}")
        context_parts.append(f"Search Scope: {search_scope} ({search_years} years)")

        user_message = (
            "Please conduct a comprehensive title search for the following property:\n\n"
            + "\n".join(context_parts)
            + "\n\nSearch all available county records online and provide complete findings."
        )

        # The 22-entity schema is large; if the model exhausts max_tokens
        # while emitting the result tool input, Anthropic returns the
        # tool_use block with an empty `input` dict. We detect that case
        # and retry once before raising so the orchestrator can mark the
        # order failed instead of silently completing with no data.
        result: dict[str, Any] = {}
        citations: list[dict[str, str]] = []
        last_attempt = 1
        for attempt in range(1, 3):
            last_attempt = attempt
            result, citations = await self.call_with_web_search(
                system_prompt=RESEARCH_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
                result_tool_schema=RESEARCH_RESULT_SCHEMA,
                result_tool_name="submit_research_results",
                result_tool_description=(
                    "Submit the complete structured title research findings. "
                    "Include all 22 entity categories with data found from web searches."
                ),
                max_web_searches=15,
                max_tokens=24576,
                temperature=0.0,
                timeout=300,
            )
            if result:
                break
            logger.warning(
                f"Title research returned empty result for {property_address} "
                f"(attempt {attempt}/2) — retrying"
            )

        if not result:
            raise RuntimeError(
                f"Title research returned empty result for {property_address}, "
                f"{county} County, {state_code} after {last_attempt} attempt(s). "
                f"Claude likely exhausted max_tokens before completing the structured tool input."
            )

        logger.info(
            f"Title research completed for {property_address}, {county} County, {state_code} "
            f"— {len(citations)} sources cited"
        )

        return result, citations
