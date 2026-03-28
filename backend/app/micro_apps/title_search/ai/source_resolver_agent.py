import uuid
import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.micro_apps.title_search.models.county_source import TACountySource
from app.micro_apps.title_search.models.source_assignment import TASourceAssignment

logger = logging.getLogger(__name__)


@dataclass
class PortalConfig:
    """Built-in portal configuration for a county."""
    portal_type: str  # "beacon" | "generic_web"
    portal_url: str
    search_config: dict | None = None


# Built-in county portal registry.
# Used as fallback when no TACountySource is pre-configured in the DB.
# Keys are (county_name, state_code) tuples.
COUNTY_PORTAL_REGISTRY: dict[tuple[str, str], PortalConfig] = {
    # --- Florida: Beacon portals (Schneider Geospatial) ---
    ("Hendry", "FL"): PortalConfig(
        portal_type="beacon",
        portal_url="https://beacon.schneidercorp.com/Application.aspx?AppID=1105",
        search_config={"app_id": "1105", "layer_id": "27399", "page_id": "11143"},
    ),
    ("Glades", "FL"): PortalConfig(
        portal_type="beacon",
        portal_url="https://beacon.schneidercorp.com/Application.aspx?AppID=513",
        search_config={"app_id": "513", "layer_id": "12584", "page_id": "6793"},
    ),
    ("Okeechobee", "FL"): PortalConfig(
        portal_type="beacon",
        portal_url="https://beacon.schneidercorp.com/Application.aspx?AppID=830",
        search_config={"app_id": "830", "layer_id": "20498", "page_id": "9321"},
    ),
    ("Highlands", "FL"): PortalConfig(
        portal_type="beacon",
        portal_url="https://beacon.schneidercorp.com/Application.aspx?AppID=737",
        search_config={"app_id": "737", "layer_id": "17966", "page_id": "8455"},
    ),
    # --- Florida: County-owned portals (generic_web) ---
    ("Duval", "FL"): PortalConfig(
        portal_type="generic_web",
        portal_url="https://or.duvalclerk.com/search?q={address}",
    ),
    ("Miami-Dade", "FL"): PortalConfig(
        portal_type="generic_web",
        portal_url="https://www.miamidade.gov/Apps/PA/PApublicServiceSearch/PropertySearch.aspx?Street={address}",
    ),
    ("Broward", "FL"): PortalConfig(
        portal_type="generic_web",
        portal_url="https://web.bcpa.net/BcpaClient/#/Record-Search?address={address}",
    ),
    ("Palm Beach", "FL"): PortalConfig(
        portal_type="generic_web",
        portal_url="https://www.pbcgov.org/papa/Asps/PropertyDetail/PropertyDetail.aspx?search={address}",
    ),
    ("Hillsborough", "FL"): PortalConfig(
        portal_type="generic_web",
        portal_url="https://gis.hcpafl.org/propertysearch/#/search/address/{address}",
    ),
    ("Orange", "FL"): PortalConfig(
        portal_type="generic_web",
        portal_url="https://www.ocpafl.org/Searches/ParcelSearch.aspx?SearchString={address}",
    ),
    ("Pinellas", "FL"): PortalConfig(
        portal_type="generic_web",
        portal_url="https://www.pcpao.org/general_search.php?search={address}",
    ),
    ("Lee", "FL"): PortalConfig(
        portal_type="generic_web",
        portal_url="https://www.leepa.org/Search/PropertySearch.aspx?SearchText={address}",
    ),
    ("Brevard", "FL"): PortalConfig(
        portal_type="generic_web",
        portal_url="https://www.bcpao.us/PropertySearch/#/search/address/{address}",
    ),
    ("Volusia", "FL"): PortalConfig(
        portal_type="generic_web",
        portal_url="https://vcpa.vcgov.org/propertycard/search?search={address}",
    ),
}

# Backward-compat alias
BEACON_REGISTRY: dict[tuple[str, str], dict] = {
    k: v.search_config
    for k, v in COUNTY_PORTAL_REGISTRY.items()
    if v.portal_type == "beacon" and v.search_config
}


async def resolve_sources_for_order(
    db: AsyncSession,
    org_id: uuid.UUID,
    order_id: uuid.UUID,
    county: str,
    state_code: str,
) -> list[TASourceAssignment]:
    """Resolve county sources and create assignments.

    1. Check for pre-configured TACountySource records in DB.
    2. If none found, check the built-in COUNTY_PORTAL_REGISTRY for known
       portals and auto-create a TACountySource record.
    3. If still no match, create a generic web search assignment so the
       pipeline can attempt a fetch rather than pausing.
    """
    result = await db.execute(
        select(TACountySource).where(
            TACountySource.county == county,
            TACountySource.state_code == state_code,
            TACountySource.is_active == True,
        )
    )
    county_sources = list(result.scalars().all())

    # Fallback: auto-create from built-in registry if no DB config exists
    if not county_sources:
        portal = COUNTY_PORTAL_REGISTRY.get((county, state_code))
        if portal:
            cs = TACountySource(
                county=county,
                state_code=state_code,
                source_type="recorder",
                availability="digital",
                portal_type=portal.portal_type,
                portal_url=portal.portal_url,
                search_config=portal.search_config,
                is_active=True,
            )
            db.add(cs)
            await db.flush()
            county_sources = [cs]
            logger.info(
                f"Auto-created {portal.portal_type} county source for "
                f"{county}, {state_code}"
            )
        else:
            logger.info(
                f"No county source configured for {county}, {state_code} — "
                "creating generic web search assignment"
            )

    assignments = []
    for cs in county_sources:
        assignment = TASourceAssignment(
            org_id=org_id,
            order_id=order_id,
            source_type=cs.source_type,
            availability=cs.availability,
            portal_config_id=cs.id,
            status="pending",
        )
        db.add(assignment)
        assignments.append(assignment)

    if not county_sources:
        # No known portal — create a digital assignment without portal_config.
        # stage_retrieve will mark it as failed (no portal config), and the
        # pipeline will fail with a clear error rather than pausing forever.
        assignment = TASourceAssignment(
            org_id=org_id,
            order_id=order_id,
            source_type="recorder",
            availability="digital",
            status="pending",
        )
        db.add(assignment)
        assignments.append(assignment)

    await db.flush()
    return assignments
