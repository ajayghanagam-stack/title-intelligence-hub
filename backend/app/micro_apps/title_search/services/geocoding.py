"""Geocoding service using US Census Bureau Geocoder API.

Converts a property address into county, state, FIPS code, and coordinates.
Free API, no key required.
"""

import logging
import httpx

logger = logging.getLogger(__name__)

CENSUS_GEOCODER_URL = "https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress"


async def geocode_address(address: str) -> dict | None:
    """Geocode an address using the US Census Bureau API.

    Returns dict with keys:
        matched_address, county, state_code, county_fips, state_fips,
        latitude, longitude
    Or None if no match found.
    """
    params = {
        "address": address,
        "benchmark": "Public_AR_Current",
        "vintage": "Current_Current",
        "format": "json",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.get(CENSUS_GEOCODER_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error(f"Geocoding failed for '{address}': {e}")
            return None

    matches = data.get("result", {}).get("addressMatches", [])
    if not matches:
        logger.warning(f"No geocoding match for '{address}'")
        return None

    match = matches[0]
    coords = match.get("coordinates", {})
    geographies = match.get("geographies", {})
    counties = geographies.get("Counties", [])

    if not counties:
        logger.warning(f"No county data in geocoding result for '{address}'")
        return None

    county_info = counties[0]
    county_name = county_info.get("NAME", "").replace(" County", "")

    return {
        "matched_address": match.get("matchedAddress", ""),
        "county": county_name,
        "state_code": _fips_to_state(county_info.get("STATE", "")),
        "county_fips": county_info.get("COUNTY", ""),
        "state_fips": county_info.get("STATE", ""),
        "fips": county_info.get("GEOID", ""),
        "latitude": coords.get("y"),
        "longitude": coords.get("x"),
    }


# FIPS state code to 2-letter abbreviation mapping
_FIPS_STATE_MAP = {
    "01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA",
    "08": "CO", "09": "CT", "10": "DE", "11": "DC", "12": "FL",
    "13": "GA", "15": "HI", "16": "ID", "17": "IL", "18": "IN",
    "19": "IA", "20": "KS", "21": "KY", "22": "LA", "23": "ME",
    "24": "MD", "25": "MA", "26": "MI", "27": "MN", "28": "MS",
    "29": "MO", "30": "MT", "31": "NE", "32": "NV", "33": "NH",
    "34": "NJ", "35": "NM", "36": "NY", "37": "NC", "38": "ND",
    "39": "OH", "40": "OK", "41": "OR", "42": "PA", "44": "RI",
    "45": "SC", "46": "SD", "47": "TN", "48": "TX", "49": "UT",
    "50": "VT", "51": "VA", "53": "WA", "54": "WV", "55": "WI",
    "56": "WY",
}


def _fips_to_state(fips: str) -> str:
    return _FIPS_STATE_MAP.get(fips, "")
