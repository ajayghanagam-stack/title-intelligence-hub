"""HTTP-based county data fetcher.

Fetches property data from county property appraiser / recorder portals.
Uses a shared httpx.AsyncClient with connection pooling and granular timeouts.

Supported portal types:
- beacon: Schneider Geospatial Beacon platform (many FL counties)
- generic_web: Simple HTTP GET with configurable URL template
"""

import time
import asyncio
import logging
from dataclasses import dataclass
from urllib.parse import quote_plus

import httpx

from app.micro_apps.title_search.models.county_source import TACountySource

logger = logging.getLogger(__name__)

CONNECT_TIMEOUT = 30  # seconds — government portals can be very slow
READ_TIMEOUT = 30  # seconds — allow time for server-side query
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
MAX_FETCH_CONCURRENCY = 4  # max parallel fetches (used by orchestrator)
MAX_RETRIES = 2  # retry once on timeout/transient errors
RETRY_BACKOFF = 3  # seconds between retries
MIN_CONTENT_LENGTH = 500  # minimum HTML length to consider a fetch successful

# Keywords that indicate the fetched page contains property data (not just a search form)
PROPERTY_KEYWORDS = [
    "parcel", "owner", "deed", "mortgage", "assessed", "tax",
    "property", "legal description", "land value", "improvement",
    "grantor", "grantee", "recording", "instrument", "book", "page",
    "subdivision", "lot", "block", "plat", "section", "township",
    "mailing address", "site address", "folio", "account",
]
MIN_KEYWORD_MATCHES = 3  # need at least this many keyword matches


@dataclass
class FetchResult:
    content: str = ""
    content_format: str = "html"
    source_url: str = ""
    success: bool = False
    error: str | None = None
    elapsed_seconds: float = 0.0


class CountyDataFetcher:
    """Fetch property data from county portal websites.

    Reuses a shared httpx.AsyncClient for connection pooling across fetches.
    Must be used as an async context manager or call close() when done.
    """

    def __init__(
        self,
        connect_timeout: int = CONNECT_TIMEOUT,
        read_timeout: int = READ_TIMEOUT,
    ):
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=connect_timeout,
                read=read_timeout,
                write=read_timeout,
                pool=read_timeout,
            ),
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        )

    async def close(self):
        await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()

    async def fetch(
        self,
        county_source: TACountySource,
        address: str,
        parcel: str | None = None,
    ) -> FetchResult:
        """Fetch property data from a county portal.

        Dispatches to the appropriate portal-type handler based on
        county_source.portal_type. Retries on transient errors (timeouts).
        """
        portal_type = county_source.portal_type or "generic_web"
        county_label = f"{county_source.county} {county_source.state_code}"
        last_result: FetchResult | None = None

        for attempt in range(MAX_RETRIES):
            start = time.monotonic()
            try:
                if portal_type == "beacon":
                    result = await self._fetch_beacon(county_source, address, parcel)
                else:
                    result = await self._fetch_generic_web(county_source, address, parcel)
                result.elapsed_seconds = round(time.monotonic() - start, 3)

                if result.success:
                    logger.info(
                        f"County fetch OK for {county_label} "
                        f"in {result.elapsed_seconds}s (attempt {attempt + 1})"
                    )
                    return result
                # Non-timeout failure — don't retry
                logger.info(
                    f"County fetch FAIL for {county_label} "
                    f"in {result.elapsed_seconds}s: {result.error}"
                )
                return result
            except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.TimeoutException) as e:
                elapsed = round(time.monotonic() - start, 3)
                err_type = type(e).__name__
                msg = f"{err_type} ({elapsed}s) for {county_label} portal"
                logger.warning(
                    f"{msg} (attempt {attempt + 1}/{MAX_RETRIES})"
                )
                last_result = FetchResult(success=False, error=msg, elapsed_seconds=elapsed)
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(RETRY_BACKOFF)
                    continue
            except httpx.HTTPStatusError as e:
                elapsed = round(time.monotonic() - start, 3)
                msg = f"HTTP {e.response.status_code} from {county_label} portal ({elapsed}s)"
                logger.warning(msg)
                return FetchResult(success=False, error=msg, elapsed_seconds=elapsed)
            except Exception as e:
                elapsed = round(time.monotonic() - start, 3)
                msg = f"Error fetching from {county_label} ({elapsed}s): {e}"
                logger.warning(msg)
                return FetchResult(success=False, error=msg, elapsed_seconds=elapsed)

        return last_result or FetchResult(success=False, error=f"All {MAX_RETRIES} attempts failed for {county_label}")

    async def _fetch_beacon(
        self,
        county_source: TACountySource,
        address: str,
        parcel: str | None = None,
    ) -> FetchResult:
        """Fetch from a Schneider Geospatial Beacon portal.

        Beacon portals use a REST API with app_id, layer_id, page_id
        from search_config. The search hits an address search endpoint
        and then fetches the detail page.
        """
        config = county_source.search_config or {}
        app_id = config.get("app_id", "")
        layer_id = config.get("layer_id", "")
        page_id = config.get("page_id", "")

        if not app_id:
            return FetchResult(
                success=False,
                error=f"Beacon config missing app_id for {county_source.county}",
            )

        # Step 1: Search for the address via Beacon search endpoint
        search_url = (
            f"https://beacon.schneidercorp.com/api/search?"
            f"appId={app_id}&layerId={layer_id}&searchText={quote_plus(address)}"
        )

        search_resp = await self._client.get(search_url)
        search_resp.raise_for_status()

        # Step 2: Get detail page
        detail_url = (
            f"https://beacon.schneidercorp.com/Application.aspx?"
            f"AppID={app_id}&PageTypeID={page_id}&PageID={page_id}"
        )
        if parcel:
            detail_url += f"&KeyValue={quote_plus(parcel)}"
        else:
            detail_url = (
                f"https://beacon.schneidercorp.com/Application.aspx?"
                f"AppID={app_id}&LayerID={layer_id}&PageTypeID={page_id}"
                f"&PageID={page_id}&Q={quote_plus(address)}"
            )

        detail_resp = await self._client.get(detail_url)
        detail_resp.raise_for_status()

        return FetchResult(
            content=detail_resp.text,
            content_format="html",
            source_url=detail_url,
            success=True,
        )

    async def _fetch_generic_web(
        self,
        county_source: TACountySource,
        address: str,
        parcel: str | None = None,
    ) -> FetchResult:
        """Fetch from a generic web portal using portal_url as template.

        The portal_url may contain {address} and {parcel} placeholders.
        """
        url = county_source.portal_url or ""
        if not url:
            return FetchResult(
                success=False,
                error=f"No portal_url configured for {county_source.county}",
            )

        # Substitute placeholders
        url = url.replace("{address}", quote_plus(address))
        url = url.replace("{parcel}", quote_plus(parcel or ""))

        resp = await self._client.get(url)
        resp.raise_for_status()

        content = resp.text
        valid, reason = validate_content(content)
        if not valid:
            return FetchResult(
                success=False,
                error=f"Portal returned no useful property data: {reason}",
                source_url=url,
            )

        return FetchResult(
            content=content,
            content_format="html",
            source_url=url,
            success=True,
        )

    async def fetch_url(self, url: str) -> FetchResult:
        """Fetch a raw URL directly (used by portal discovery). Retries on timeout."""
        last_result: FetchResult | None = None
        for attempt in range(MAX_RETRIES):
            start = time.monotonic()
            try:
                resp = await self._client.get(url)
                resp.raise_for_status()
                content = resp.text
                valid, reason = validate_content(content)
                elapsed = round(time.monotonic() - start, 3)
                if not valid:
                    return FetchResult(
                        success=False,
                        error=f"No useful property data: {reason}",
                        source_url=url,
                        elapsed_seconds=elapsed,
                    )
                return FetchResult(
                    content=content,
                    content_format="html",
                    source_url=url,
                    success=True,
                    elapsed_seconds=elapsed,
                )
            except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.TimeoutException):
                elapsed = round(time.monotonic() - start, 3)
                last_result = FetchResult(
                    success=False,
                    error=f"Timeout ({elapsed}s) fetching {url}",
                    source_url=url,
                    elapsed_seconds=elapsed,
                )
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(RETRY_BACKOFF)
                    continue
            except Exception as e:
                elapsed = round(time.monotonic() - start, 3)
                return FetchResult(
                    success=False,
                    error=str(e),
                    source_url=url,
                    elapsed_seconds=elapsed,
                )
        return last_result or FetchResult(
            success=False, error=f"All {MAX_RETRIES} attempts failed", source_url=url,
        )


def validate_content(html: str) -> tuple[bool, str]:
    """Check if fetched HTML contains actual property data.

    Returns (is_valid, reason) tuple.
    """
    if len(html) < MIN_CONTENT_LENGTH:
        return False, f"Content too short ({len(html)} chars)"

    html_lower = html.lower()
    matches = sum(1 for kw in PROPERTY_KEYWORDS if kw in html_lower)
    if matches < MIN_KEYWORD_MATCHES:
        return False, f"Only {matches} property keywords found (need {MIN_KEYWORD_MATCHES})"

    return True, "OK"
