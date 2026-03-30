"""Seed TACountySource records for supported Florida counties.

Usage:
    cd backend && python scripts/seed_county_sources.py
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.config import get_settings
from app.micro_apps.title_search.models.county_source import TACountySource

# Beacon-based FL county sources
# Each entry: (county, state_code, source_type, availability, portal_type, portal_url, search_config)
COUNTY_SOURCES = [
    {
        "county": "Hendry",
        "state_code": "FL",
        "source_type": "recorder",
        "availability": "digital",
        "portal_type": "beacon",
        "portal_url": "https://beacon.schneidercorp.com/Application.aspx?AppID=1105",
        "search_config": {
            "app_id": "1105",
            "layer_id": "27399",
            "page_id": "11143",
        },
    },
    {
        "county": "Glades",
        "state_code": "FL",
        "source_type": "recorder",
        "availability": "digital",
        "portal_type": "beacon",
        "portal_url": "https://beacon.schneidercorp.com/Application.aspx?AppID=513",
        "search_config": {
            "app_id": "513",
            "layer_id": "12584",
            "page_id": "6793",
        },
    },
    {
        "county": "Okeechobee",
        "state_code": "FL",
        "source_type": "recorder",
        "availability": "digital",
        "portal_type": "beacon",
        "portal_url": "https://beacon.schneidercorp.com/Application.aspx?AppID=830",
        "search_config": {
            "app_id": "830",
            "layer_id": "20498",
            "page_id": "9321",
        },
    },
    {
        "county": "Highlands",
        "state_code": "FL",
        "source_type": "recorder",
        "availability": "digital",
        "portal_type": "beacon",
        "portal_url": "https://beacon.schneidercorp.com/Application.aspx?AppID=737",
        "search_config": {
            "app_id": "737",
            "layer_id": "17966",
            "page_id": "8455",
        },
    },
    {
        "county": "Duval",
        "state_code": "FL",
        "source_type": "property_appraiser",
        "availability": "digital",
        "portal_type": "generic_web",
        "portal_url": "https://paopropertysearch.coj.net/Basic/Search.aspx?SearchText={address}",
        "search_config": {},
    },
    {
        "county": "Duval",
        "state_code": "FL",
        "source_type": "recorder",
        "availability": "digital",
        "portal_type": "generic_web",
        "portal_url": "https://or.duvalclerk.com/search?q={address}",
        "search_config": {},
    },
]


async def seed():
    settings = get_settings()
    engine = create_async_engine(str(settings.effective_database_url))
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as db:
        for src in COUNTY_SOURCES:
            existing = (await db.execute(
                select(TACountySource).where(
                    TACountySource.county == src["county"],
                    TACountySource.state_code == src["state_code"],
                    TACountySource.source_type == src["source_type"],
                )
            )).scalar_one_or_none()

            if existing:
                # Update existing
                existing.portal_type = src["portal_type"]
                existing.portal_url = src["portal_url"]
                existing.search_config = src["search_config"]
                existing.availability = src["availability"]
                existing.is_active = True
                print(f"  Updated: {src['county']} County, {src['state_code']}")
            else:
                db.add(TACountySource(
                    county=src["county"],
                    state_code=src["state_code"],
                    source_type=src["source_type"],
                    availability=src["availability"],
                    portal_type=src["portal_type"],
                    portal_url=src["portal_url"],
                    search_config=src["search_config"],
                    is_active=True,
                ))
                print(f"  Created: {src['county']} County, {src['state_code']}")

        await db.commit()

    await engine.dispose()
    print(f"\nSeeded {len(COUNTY_SOURCES)} county sources.")


if __name__ == "__main__":
    asyncio.run(seed())
