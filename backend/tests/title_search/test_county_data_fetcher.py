"""Tests for CountyDataFetcher."""
import pytest
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock, patch

from app.micro_apps.title_search.services.county_data_fetcher import (
    CountyDataFetcher,
    FetchResult,
)


@dataclass
class MockCountySource:
    """Lightweight stand-in for TACountySource (avoids SQLAlchemy instrumentation)."""
    county: str = "Hendry"
    state_code: str = "FL"
    source_type: str = "recorder"
    availability: str = "digital"
    portal_type: str | None = "beacon"
    portal_url: str | None = "https://beacon.schneidercorp.com/Application.aspx?AppID=1105"
    search_config: dict | None = field(default_factory=lambda: {"app_id": "1105", "layer_id": "27399", "page_id": "11143"})


def _make_beacon_source() -> MockCountySource:
    return MockCountySource()


def _make_generic_source() -> MockCountySource:
    return MockCountySource(
        county="Duval",
        portal_type="generic_web",
        portal_url="https://example.com/search?q={address}",
        search_config={},
    )


def _make_fetcher_with_mock_client():
    """Create a CountyDataFetcher with a mocked httpx client."""
    mock_client = AsyncMock()
    mock_client.aclose = AsyncMock()

    fetcher = CountyDataFetcher.__new__(CountyDataFetcher)
    fetcher._client = mock_client
    return fetcher, mock_client


@pytest.mark.asyncio
async def test_fetch_beacon_success():
    """Beacon fetch returns HTML on success."""
    fetcher, mock_client = _make_fetcher_with_mock_client()
    source = _make_beacon_source()

    mock_response = MagicMock()
    mock_response.text = "<html><body>Property Data</body></html>"
    mock_response.raise_for_status = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_response)

    result = await fetcher.fetch(source, "123 Main St, LaBelle, FL")

    assert result.success is True
    assert result.content_format == "html"
    assert "Property Data" in result.content
    assert result.source_url != ""
    assert result.elapsed_seconds >= 0


@pytest.mark.asyncio
async def test_fetch_generic_web_success():
    """Generic web fetch returns HTML on success."""
    fetcher, mock_client = _make_fetcher_with_mock_client()
    source = _make_generic_source()

    # Content must pass validation: >=500 chars + >=3 property keywords
    mock_html = (
        "<html><body>"
        "<h1>Duval County Property Appraiser</h1>"
        "<div>Owner: John Smith</div>"
        "<div>Parcel Number: 012875-1145</div>"
        "<div>Property Address: 456 Elm St, Jacksonville, FL 32210</div>"
        "<div>Legal Description: LOT 12 BLK 5 ARLINGTON MANOR UNIT 3</div>"
        "<div>Assessed Land Value: $45,000</div>"
        "<div>Improvement Value: $120,000</div>"
        "<div>Tax Amount: $3,200</div>"
        "<div>Deed Book/Page: 1234/567</div>"
        "<div>Recording Date: 01/15/2020</div>"
        + "x" * 200  # padding to exceed min length
        + "</body></html>"
    )
    mock_response = MagicMock()
    mock_response.text = mock_html
    mock_response.raise_for_status = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_response)

    result = await fetcher.fetch(source, "456 Elm St, Jacksonville, FL")

    assert result.success is True
    assert "Duval County" in result.content


@pytest.mark.asyncio
async def test_fetch_timeout():
    """Fetch retries on timeout and returns error after all attempts."""
    import httpx

    fetcher, mock_client = _make_fetcher_with_mock_client()
    source = _make_beacon_source()
    mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timed out"))

    with patch("app.micro_apps.title_search.services.county_data_fetcher.MAX_RETRIES", 1):
        result = await fetcher.fetch(source, "123 Main St")

    assert result.success is False
    assert "imeout" in (result.error or "")
    assert result.elapsed_seconds >= 0


@pytest.mark.asyncio
async def test_fetch_connect_timeout():
    """Fetch retries on connect timeout."""
    import httpx

    fetcher, mock_client = _make_fetcher_with_mock_client()
    source = _make_beacon_source()
    mock_client.get = AsyncMock(side_effect=httpx.ConnectTimeout("connect timeout"))

    with patch("app.micro_apps.title_search.services.county_data_fetcher.MAX_RETRIES", 1):
        result = await fetcher.fetch(source, "123 Main St")

    assert result.success is False
    assert "ConnectTimeout" in (result.error or "")


@pytest.mark.asyncio
async def test_fetch_read_timeout():
    """Fetch retries on read timeout."""
    import httpx

    fetcher, mock_client = _make_fetcher_with_mock_client()
    source = _make_beacon_source()
    mock_client.get = AsyncMock(side_effect=httpx.ReadTimeout("read timeout"))

    with patch("app.micro_apps.title_search.services.county_data_fetcher.MAX_RETRIES", 1):
        result = await fetcher.fetch(source, "123 Main St")

    assert result.success is False
    assert "ReadTimeout" in (result.error or "")


@pytest.mark.asyncio
async def test_fetch_timeout_retries():
    """Fetch retries on timeout and succeeds on second attempt."""
    import httpx

    fetcher, mock_client = _make_fetcher_with_mock_client()
    source = _make_beacon_source()

    mock_response = MagicMock()
    mock_response.text = "<html><body>Property Data</body></html>"
    mock_response.raise_for_status = MagicMock()

    # First call times out, second succeeds
    mock_client.get = AsyncMock(
        side_effect=[httpx.ConnectTimeout("timeout"), mock_response, mock_response]
    )

    with patch("app.micro_apps.title_search.services.county_data_fetcher.RETRY_BACKOFF", 0):
        result = await fetcher.fetch(source, "123 Main St, LaBelle, FL")

    assert result.success is True
    assert "Property Data" in result.content


@pytest.mark.asyncio
async def test_fetch_http_error():
    """Fetch returns error on HTTP status error."""
    import httpx

    fetcher, mock_client = _make_fetcher_with_mock_client()
    source = _make_beacon_source()

    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_client.get = AsyncMock(
        side_effect=httpx.HTTPStatusError("404", request=MagicMock(), response=mock_resp)
    )

    result = await fetcher.fetch(source, "123 Main St")

    assert result.success is False
    assert "404" in (result.error or "")


@pytest.mark.asyncio
async def test_fetch_beacon_missing_app_id():
    """Beacon fetch fails gracefully when app_id is missing."""
    fetcher, _ = _make_fetcher_with_mock_client()
    source = _make_beacon_source()
    source.search_config = {}  # No app_id

    result = await fetcher.fetch(source, "123 Main St")
    assert result.success is False
    assert "app_id" in (result.error or "").lower()


@pytest.mark.asyncio
async def test_fetch_generic_no_url():
    """Generic web fetch fails when no portal_url configured."""
    fetcher, _ = _make_fetcher_with_mock_client()
    source = _make_generic_source()
    source.portal_url = None

    result = await fetcher.fetch(source, "123 Main St")
    assert result.success is False
    assert "portal_url" in (result.error or "").lower()


@pytest.mark.asyncio
async def test_fetch_url_construction_with_parcel():
    """Beacon fetch includes parcel in URL when provided."""
    fetcher, mock_client = _make_fetcher_with_mock_client()
    source = _make_beacon_source()

    mock_response = MagicMock()
    mock_response.text = "<html>parcel data</html>"
    mock_response.raise_for_status = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_response)

    result = await fetcher.fetch(source, "123 Main St", parcel="1-29-43-01-A")

    assert result.success is True
    # Verify parcel was included in the detail URL
    calls = mock_client.get.call_args_list
    detail_call_url = str(calls[-1])
    assert "KeyValue" in detail_call_url


@pytest.mark.asyncio
async def test_context_manager():
    """CountyDataFetcher works as async context manager."""
    async with CountyDataFetcher() as fetcher:
        assert fetcher._client is not None
    # Client should be closed after exiting
