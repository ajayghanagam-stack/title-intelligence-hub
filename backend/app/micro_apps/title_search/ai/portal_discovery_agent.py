"""AI-powered county portal discovery.

When no registered portal exists or all registered portals fail for a county,
this agent asks the LLM to identify the correct property records portal URL.
The discovered URL is validated by fetching it, and if successful, saved to
the TACountySource registry for future use.
"""

import logging

from app.ai.base_service import BaseAIService

logger = logging.getLogger(__name__)

DISCOVERY_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "portals": {
            "type": "array",
            "description": "List of portal URLs to try, ordered by likelihood of having property data",
            "items": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Full URL for the county property search portal",
                    },
                    "portal_type": {
                        "type": "string",
                        "enum": ["beacon", "generic_web"],
                        "description": "Portal platform type",
                    },
                    "source_name": {
                        "type": "string",
                        "description": "Name of the data source (e.g., 'Duval County Property Appraiser')",
                    },
                    "search_config": {
                        "type": "object",
                        "description": "Beacon-specific config (app_id, layer_id, page_id) if portal_type is beacon, otherwise null",
                        "properties": {
                            "app_id": {"type": "string"},
                            "layer_id": {"type": "string"},
                            "page_id": {"type": "string"},
                        },
                    },
                },
                "required": ["url", "portal_type", "source_name"],
            },
        },
        "county_has_digital_records": {
            "type": "boolean",
            "description": "Whether this county is known to have digitized property records online",
        },
    },
    "required": ["portals", "county_has_digital_records"],
}

DISCOVERY_SYSTEM_PROMPT = """You are a title search expert who knows US county property record portals.

Given a county and state, identify the official online portals where property records
(deeds, mortgages, liens, tax assessments) can be searched by address or parcel number.

CRITICAL RULES — READ CAREFULLY:
1. ONLY return URLs for domains you are 100% certain exist. Government portal domains follow
   patterns like: {county}clerk.com, {county}pa.org, bcpa.net, coj.net, miamidade.gov.
2. NEVER invent or guess domain names. If you are not certain a domain exists, DO NOT include it.
3. Return the EXACT base domain — do NOT fabricate URL paths or query parameters.
   Use the homepage URL if you don't know the exact search endpoint.
4. Prefer well-known portal platforms: Beacon (schneidercorp.com), Tyler Technologies,
   Aumentum, Vision Government Solutions, qPublic.
5. If the county uses a JavaScript-heavy portal that requires a browser (most modern county
   sites), still return the URL — the caller will handle it.

IMPORTANT FACTS:
- Nearly ALL US counties with populations over 20,000 have digitized property records online.
- ALL 67 Florida counties have online property appraiser and clerk of court websites.
- When in doubt, set county_has_digital_records to true — the caller will verify accessibility.

Focus on:
1. County Property Appraiser / Assessor website (property details, tax records, ownership)
2. County Clerk / Recorder of Deeds (recorded documents, official records search)

For each portal, provide:
- The URL. Include {address} placeholder ONLY if you know the exact query parameter name.
  Otherwise, return the base search page URL without placeholders.
- Whether it uses the Beacon (Schneider Geospatial) platform or is a generic website.
- If Beacon, include the app_id, layer_id, and page_id from the URL parameters.

If you truly cannot identify any portal for the county, set county_has_digital_records to false."""


class PortalDiscoveryAgent(BaseAIService):
    """Discovers county property record portal URLs using AI."""

    async def discover(self, county: str, state_code: str) -> dict:
        """Ask LLM to identify property record portals for a county.

        Returns dict with 'portals' list and 'county_has_digital_records' bool.
        """
        user_prompt = (
            f"Identify the official property records portals for "
            f"{county} County, {state_code}. "
            f"I need URLs where I can search property records by address."
        )

        try:
            result = await self.call_json_structured(
                system_prompt=DISCOVERY_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
                json_schema=DISCOVERY_JSON_SCHEMA,
                max_tokens=2048,
                temperature=0.0,
            )
            portals = result.get("portals", [])
            has_digital = result.get("county_has_digital_records", False)
            logger.info(
                f"Portal discovery for {county}, {state_code}: "
                f"{len(portals)} portals found, digital={has_digital}"
            )
            return result
        except Exception as e:
            logger.warning(f"Portal discovery failed for {county}, {state_code}: {e}")
            return {"portals": [], "county_has_digital_records": False}
