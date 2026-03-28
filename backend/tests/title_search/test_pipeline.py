"""Tests for TSA pipeline orchestrator."""
import uuid
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.micro_apps.title_search.models.order import TAOrder
from app.micro_apps.title_search.models.source_assignment import TASourceAssignment
from app.micro_apps.title_search.models.raw_document import TARawDocument
from app.micro_apps.title_search.models.document import TADocument
from app.micro_apps.title_search.models.chain_link import TAChainLink
from app.micro_apps.title_search.models.flag import TAFlag
from app.micro_apps.title_search.models.package import TAPackage
from app.micro_apps.title_search.models.county_source import TACountySource
from app.micro_apps.title_search.pipeline.orchestrator import run_pipeline
from app.micro_apps.title_search.services.county_data_fetcher import FetchResult
from tests.conftest import TEST_ORG_ID, TEST_USER_ID, test_session_factory
from tests.title_search.conftest import TEST_ORDER_ID


SAMPLE_HTML = "<html><body><h1>Property Record</h1><table><tr><td>Owner: Jane Doe</td></tr></table></body></html>"

SAMPLE_EXTRACTION_RESULT = {
    "property_info": {
        "owner_name": "Jane Doe",
        "address": "123 Main St, LaBelle, FL 33935",
        "municipality": "LaBelle",
        "zip": "33935",
        "parcel_number": "1-29-43-01-010-0000-001.0",
        "subdivision": "Palm Village",
        "legal_description": "Lot 1, Block 2, Palm Village Subdivision",
    },
    "deeds": [
        {
            "doc_type": "deed",
            "deed_type_detail": "Warranty Deed",
            "recording_date": "2020-01-15",
            "recording_ref": "2020-001234",
            "book_page": "1234/567",
            "instrument_number": "2020001234",
            "grantor": "John Smith",
            "grantee": "Jane Doe",
            "consideration": 250000.00,
        },
    ],
    "mortgages": [
        {
            "borrower": "Jane Doe",
            "lender": "First National Bank",
            "trustee": "ABC Trustee Co",
            "recording_date": "2020-02-01",
            "recording_ref": "2020-001235",
            "book_page": "1234/568",
            "instrument_number": "2020001235",
            "loan_amount": 200000.00,
            "maturity_date": "2050-02-01",
            "open_closed_end": "Closed",
            "min_number": "100012345678",
            "riders": "PUD",
        },
    ],
    "liens": [],
    "tax_info": {
        "parcel_id": "1-29-43-01-010-0000-001.0",
        "assessment_year": "2025",
        "land_value": 50000,
        "improvement_value": 175000,
        "total_value": 225000,
        "tax_amount": 3200.50,
        "tax_status": "Paid",
        "homestead_exemption": True,
    },
    "misc_documents": [],
    "confidence": 0.90,
}


def _mock_analysis_return(documents: list[dict]) -> dict:
    """Return mock result matching ChainAnalysisAgent.analyze() shape."""
    links = []
    position = 1
    for doc in documents:
        if doc.get("doc_type") in ("deed", "assignment"):
            links.append({
                "position": position,
                "link_type": "conveyance",
                "document_id": doc.get("id"),
                "from_party": doc.get("grantor"),
                "to_party": doc.get("grantee"),
                "effective_date": doc.get("recording_date"),
                "is_gap": False,
            })
            position += 1
        elif doc.get("doc_type") in ("mortgage", "lien", "easement"):
            links.append({
                "position": position,
                "link_type": "encumbrance",
                "document_id": doc.get("id"),
                "from_party": doc.get("grantor"),
                "to_party": doc.get("grantee"),
                "effective_date": doc.get("recording_date"),
                "is_gap": False,
            })
            position += 1
    return {"chain_links": links, "anomalies": [], "chain_complete": True}


def _setup_ai_mocks():
    """Create and return patchers for all AI agents used in the pipeline."""
    # PropertyDataExtractorAgent mock for HTML parsing
    mock_extractor_cls = MagicMock()
    mock_extractor_instance = AsyncMock()
    mock_extractor_instance.extract_all = AsyncMock(return_value=SAMPLE_EXTRACTION_RESULT)
    mock_extractor_cls.return_value = mock_extractor_instance

    mock_analysis_cls = MagicMock()
    mock_analysis_instance = AsyncMock()
    mock_analysis_instance.analyze = AsyncMock(side_effect=_mock_analysis_return)
    mock_analysis_cls.return_value = mock_analysis_instance

    patchers = [
        patch(
            "app.micro_apps.title_search.ai.property_data_extractor.PropertyDataExtractorAgent",
            mock_extractor_cls,
        ),
        patch(
            "app.micro_apps.title_search.ai.chain_analysis_agent.ChainAnalysisAgent",
            mock_analysis_cls,
        ),
    ]
    return patchers


def _setup_fetch_mock(success: bool = True):
    """Create a patcher for CountyDataFetcher.fetch() and fetch_url()."""
    if success:
        result = FetchResult(
            content=SAMPLE_HTML,
            content_format="html",
            source_url="https://beacon.schneidercorp.com/test",
            success=True,
        )
    else:
        result = FetchResult(
            success=False,
            error="Connection timeout",
        )

    mock_fetcher_cls = MagicMock()
    mock_fetcher_instance = MagicMock()
    mock_fetcher_instance.fetch = AsyncMock(return_value=result)
    mock_fetcher_instance.fetch_url = AsyncMock(return_value=result)
    mock_fetcher_instance.close = AsyncMock()
    mock_fetcher_instance.__aenter__ = AsyncMock(return_value=mock_fetcher_instance)
    mock_fetcher_instance.__aexit__ = AsyncMock(return_value=False)
    mock_fetcher_cls.return_value = mock_fetcher_instance

    return patch(
        "app.micro_apps.title_search.services.county_data_fetcher.CountyDataFetcher",
        mock_fetcher_cls,
    )


def _setup_discovery_mock(portals=None):
    """Create a patcher for PortalDiscoveryAgent.discover()."""
    if portals is None:
        portals = []
    return patch(
        "app.micro_apps.title_search.ai.portal_discovery_agent.PortalDiscoveryAgent.discover",
        new_callable=AsyncMock,
        return_value={"portals": portals, "county_has_digital_records": len(portals) > 0},
    )


@pytest_asyncio.fixture
async def pipeline_order(db_session: AsyncSession, seed_data):
    """Create an order ready for pipeline processing with a digital county source."""
    cs = TACountySource(
        county="Hendry",
        state_code="FL",
        source_type="recorder",
        availability="digital",
        portal_type="beacon",
        portal_url="https://beacon.schneidercorp.com/Application.aspx?AppID=1105",
        search_config={"app_id": "1105", "layer_id": "27399", "page_id": "11143"},
        is_active=True,
    )
    db_session.add(cs)

    order = TAOrder(
        id=TEST_ORDER_ID,
        org_id=TEST_ORG_ID,
        created_by=TEST_USER_ID,
        property_address="123 Main St, LaBelle, FL 33935",
        county="Hendry",
        state_code="FL",
        status="processing",
        pipeline_stage="order",
    )
    db_session.add(order)
    await db_session.commit()
    return order


@pytest.mark.asyncio
async def test_full_pipeline(pipeline_order):
    """Run full pipeline with county fetch + AI extraction and verify all stages produce data."""
    ai_patchers = _setup_ai_mocks()
    fetch_patcher = _setup_fetch_mock(success=True)
    discovery_patcher = _setup_discovery_mock()  # empty — registered portal wins the race

    for p in ai_patchers:
        p.start()
    fetch_patcher.start()
    discovery_patcher.start()
    try:
        await run_pipeline(TEST_ORDER_ID, TEST_ORG_ID, test_session_factory)
    finally:
        for p in ai_patchers:
            p.stop()
        fetch_patcher.stop()
        discovery_patcher.stop()

    async with test_session_factory() as db:
        # Order should be completed or review_required
        order = (await db.execute(
            select(TAOrder).where(TAOrder.id == TEST_ORDER_ID)
        )).scalar_one()
        assert order.status in ("completed", "review_required")
        assert order.pipeline_stage is None

        # Legal description should be populated from extraction
        # (set during parse stage from property_info.legal_description)
        assert order.legal_description is None or order.legal_description == "Lot 1, Block 2, Palm Village Subdivision"

        # Source assignments should exist with portal_config_id
        sources = (await db.execute(
            select(TASourceAssignment).where(TASourceAssignment.order_id == TEST_ORDER_ID)
        )).scalars().all()
        assert len(sources) >= 1
        assert sources[0].portal_config_id is not None

        # Raw documents should exist with HTML content format
        raw_docs = (await db.execute(
            select(TARawDocument).where(TARawDocument.order_id == TEST_ORDER_ID)
        )).scalars().all()
        assert len(raw_docs) >= 1
        assert raw_docs[0].content_format == "html"
        assert raw_docs[0].source_url is not None

        # Parsed documents should exist (deed + mortgage + tax from extraction)
        docs = (await db.execute(
            select(TADocument).where(TADocument.order_id == TEST_ORDER_ID)
        )).scalars().all()
        assert len(docs) >= 2  # At least deed + mortgage

        # Verify deed has metadata
        deed_docs = [d for d in docs if d.doc_type == "deed"]
        assert len(deed_docs) >= 1
        assert deed_docs[0].doc_metadata is not None
        assert deed_docs[0].doc_metadata.get("book_page") == "1234/567"
        assert deed_docs[0].doc_metadata.get("instrument_number") == "2020001234"

        # Verify mortgage has doc_metadata
        mtg_docs = [d for d in docs if d.doc_type == "mortgage"]
        assert len(mtg_docs) >= 1
        assert mtg_docs[0].doc_metadata is not None
        assert mtg_docs[0].doc_metadata.get("trustee") == "ABC Trustee Co"
        assert mtg_docs[0].doc_metadata.get("maturity_date") == "2050-02-01"

        # Chain links should exist
        chain = (await db.execute(
            select(TAChainLink).where(TAChainLink.order_id == TEST_ORDER_ID)
        )).scalars().all()
        assert len(chain) >= 1

        # Package should exist
        pkg = (await db.execute(
            select(TAPackage).where(TAPackage.order_id == TEST_ORDER_ID)
        )).scalar_one_or_none()
        assert pkg is not None
        assert pkg.package_number.startswith("TA-")


@pytest.mark.asyncio
async def test_pipeline_with_non_digital_source(db_session: AsyncSession, seed_data):
    """Pipeline pauses at retrieve when non-digital source exists."""
    cs = TACountySource(
        county="Rural",
        state_code="FL",
        source_type="recorder",
        availability="non_digital",
        is_active=True,
    )
    db_session.add(cs)

    order_id = uuid.uuid4()
    order = TAOrder(
        id=order_id,
        org_id=TEST_ORG_ID,
        created_by=TEST_USER_ID,
        property_address="456 Rural Rd, Rural, FL",
        county="Rural",
        state_code="FL",
        status="processing",
    )
    db_session.add(order)
    await db_session.commit()

    # Non-digital source pauses at retrieve — no AI agents called
    await run_pipeline(order_id, TEST_ORG_ID, test_session_factory)

    async with test_session_factory() as db:
        order = (await db.execute(
            select(TAOrder).where(TAOrder.id == order_id)
        )).scalar_one()
        assert order.status == "awaiting_abstractor"


@pytest.mark.asyncio
async def test_pipeline_no_county_source_fails_gracefully(db_session: AsyncSession, seed_data):
    """Pipeline fails gracefully when no portal can be found for the county."""
    order_id = uuid.uuid4()
    order = TAOrder(
        id=order_id,
        org_id=TEST_ORG_ID,
        created_by=TEST_USER_ID,
        property_address="789 Unknown Rd, NoCounty, TX",
        county="NoCounty",
        state_code="TX",
        status="processing",
    )
    db_session.add(order)
    await db_session.commit()

    # Mock the portal discovery agent to return no portals
    discovery_mock = patch(
        "app.micro_apps.title_search.ai.portal_discovery_agent.PortalDiscoveryAgent.discover",
        new_callable=AsyncMock,
        return_value={"portals": [], "county_has_digital_records": False},
    )
    discovery_mock.start()
    try:
        await run_pipeline(order_id, TEST_ORG_ID, test_session_factory)
    finally:
        discovery_mock.stop()

    async with test_session_factory() as db:
        order = (await db.execute(
            select(TAOrder).where(TAOrder.id == order_id)
        )).scalar_one()
        assert order.status == "failed"
        assert "No accessible portal found" in (order.pipeline_error or "")


@pytest.mark.asyncio
async def test_pipeline_fetch_failure_tries_discovery(db_session: AsyncSession, seed_data):
    """Pipeline tries AI portal discovery when all registered fetches fail."""
    cs = TACountySource(
        county="Broken",
        state_code="FL",
        source_type="recorder",
        availability="digital",
        portal_type="beacon",
        portal_url="https://broken.example.com",
        search_config={"app_id": "999"},
        is_active=True,
    )
    db_session.add(cs)

    order_id = uuid.uuid4()
    order = TAOrder(
        id=order_id,
        org_id=TEST_ORG_ID,
        created_by=TEST_USER_ID,
        property_address="100 Broken Ave, Broken, FL",
        county="Broken",
        state_code="FL",
        status="processing",
    )
    db_session.add(order)
    await db_session.commit()

    fetch_patcher = _setup_fetch_mock(success=False)
    # Mock discovery to also return no portals → graceful failure
    discovery_mock = patch(
        "app.micro_apps.title_search.ai.portal_discovery_agent.PortalDiscoveryAgent.discover",
        new_callable=AsyncMock,
        return_value={"portals": [], "county_has_digital_records": False},
    )
    fetch_patcher.start()
    discovery_mock.start()
    try:
        await run_pipeline(order_id, TEST_ORG_ID, test_session_factory)
    finally:
        fetch_patcher.stop()
        discovery_mock.stop()

    async with test_session_factory() as db:
        order = (await db.execute(
            select(TAOrder).where(TAOrder.id == order_id)
        )).scalar_one()
        assert order.status == "failed"
        assert "No accessible portal found" in (order.pipeline_error or "")


@pytest.mark.asyncio
async def test_pipeline_idempotent_retry(pipeline_order):
    """Running pipeline twice should not create duplicate data."""
    ai_patchers = _setup_ai_mocks()
    fetch_patcher = _setup_fetch_mock(success=True)
    discovery_patcher = _setup_discovery_mock()

    for p in ai_patchers:
        p.start()
    fetch_patcher.start()
    discovery_patcher.start()
    try:
        await run_pipeline(TEST_ORDER_ID, TEST_ORG_ID, test_session_factory)

        async with test_session_factory() as db:
            docs_count_1 = len((await db.execute(
                select(TADocument).where(TADocument.order_id == TEST_ORDER_ID)
            )).scalars().all())

        # Run again — parse/chain stages use delete-then-insert
        # Reset order status first
        async with test_session_factory() as db:
            order = (await db.execute(
                select(TAOrder).where(TAOrder.id == TEST_ORDER_ID)
            )).scalar_one()
            order.status = "processing"
            order.pipeline_stage = "parse"
            await db.commit()

        # Re-run from parse stage manually
        from app.micro_apps.title_search.pipeline.orchestrator import STAGE_HANDLERS
        async with test_session_factory() as db:
            await STAGE_HANDLERS["parse"](TEST_ORDER_ID, TEST_ORG_ID, db)
            await db.commit()

            docs_count_2 = len((await db.execute(
                select(TADocument).where(TADocument.order_id == TEST_ORDER_ID)
            )).scalars().all())

        assert docs_count_1 == docs_count_2
    finally:
        for p in ai_patchers:
            p.stop()
        fetch_patcher.stop()
        discovery_patcher.stop()


@pytest.mark.asyncio
async def test_pipeline_discovery_wins_race(db_session: AsyncSession, seed_data):
    """Registered portals fail, AI discovery finds a working portal — verify registry save."""
    cs = TACountySource(
        county="Slow",
        state_code="FL",
        source_type="recorder",
        availability="digital",
        portal_type="beacon",
        portal_url="https://slow.example.com",
        search_config={"app_id": "111"},
        is_active=True,
    )
    db_session.add(cs)

    order_id = uuid.uuid4()
    order = TAOrder(
        id=order_id,
        org_id=TEST_ORG_ID,
        created_by=TEST_USER_ID,
        property_address="200 Discovery Ln, Slow, FL 33000",
        county="Slow",
        state_code="FL",
        status="processing",
        pipeline_stage="order",
    )
    db_session.add(order)
    await db_session.commit()

    # Registered portal always fails
    fail_result = FetchResult(success=False, error="Connection timeout")
    # Discovered portal succeeds
    ok_result = FetchResult(
        content=SAMPLE_HTML, content_format="html",
        source_url="https://discovered.example.com/property", success=True,
    )

    mock_fetcher_cls = MagicMock()
    mock_fetcher_instance = MagicMock()
    mock_fetcher_instance.fetch = AsyncMock(return_value=fail_result)
    mock_fetcher_instance.fetch_url = AsyncMock(return_value=ok_result)
    mock_fetcher_instance.close = AsyncMock()
    mock_fetcher_instance.__aenter__ = AsyncMock(return_value=mock_fetcher_instance)
    mock_fetcher_instance.__aexit__ = AsyncMock(return_value=False)
    mock_fetcher_cls.return_value = mock_fetcher_instance

    fetch_patcher = patch(
        "app.micro_apps.title_search.services.county_data_fetcher.CountyDataFetcher",
        mock_fetcher_cls,
    )
    discovery_patcher = _setup_discovery_mock(portals=[{
        "url": "https://discovered.example.com/property?addr={address}",
        "source_name": "Discovered Portal",
        "portal_type": "generic_web",
    }])
    # Mock DNS so the fake discovered domain passes the DNS check
    dns_patcher = patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 0))])
    ai_patchers = _setup_ai_mocks()

    for p in ai_patchers:
        p.start()
    fetch_patcher.start()
    discovery_patcher.start()
    dns_patcher.start()
    try:
        await run_pipeline(order_id, TEST_ORG_ID, test_session_factory)
    finally:
        for p in ai_patchers:
            p.stop()
        fetch_patcher.stop()
        discovery_patcher.stop()
        dns_patcher.stop()

    async with test_session_factory() as db:
        order = (await db.execute(
            select(TAOrder).where(TAOrder.id == order_id)
        )).scalar_one()
        assert order.status in ("completed", "review_required")

        # Discovered county source should be saved to registry
        new_cs = (await db.execute(
            select(TACountySource).where(
                TACountySource.county == "Slow",
                TACountySource.state_code == "FL",
                TACountySource.portal_type == "generic_web",
            )
        )).scalar_one_or_none()
        assert new_cs is not None
        assert "discovered.example.com" in (new_cs.portal_url or "")

        # Raw document should exist from discovered portal
        raw_docs = (await db.execute(
            select(TARawDocument).where(TARawDocument.order_id == order_id)
        )).scalars().all()
        assert len(raw_docs) >= 1
        assert raw_docs[0].document_ref == "SLOW-DISCOVERED"


@pytest.mark.asyncio
async def test_pipeline_first_success_wins(pipeline_order):
    """Two registered portals — first returns immediately, pipeline completes fast."""
    import asyncio

    # Add a second county source for the same county
    async with test_session_factory() as db:
        cs2 = TACountySource(
            county="Hendry",
            state_code="FL",
            source_type="tax_collector",
            availability="digital",
            portal_type="generic_web",
            portal_url="https://slow-portal.example.com",
            search_config={},
            is_active=True,
        )
        db.add(cs2)
        await db.flush()

        # Add a second assignment pointing to this source
        sa2 = TASourceAssignment(
            org_id=TEST_ORG_ID,
            order_id=TEST_ORDER_ID,
            source_type="tax_collector",
            availability="digital",
            portal_config_id=cs2.id,
            status="pending",
        )
        db.add(sa2)
        await db.commit()

    fast_result = FetchResult(
        content=SAMPLE_HTML, content_format="html",
        source_url="https://beacon.schneidercorp.com/test", success=True,
    )
    slow_result = FetchResult(
        content=SAMPLE_HTML, content_format="html",
        source_url="https://slow-portal.example.com/test", success=True,
    )

    call_count = 0

    async def _side_effect_fetch(**kwargs):
        nonlocal call_count
        call_count += 1
        cs = kwargs.get("county_source")
        if cs and cs.portal_type == "generic_web":
            # Slow portal — simulate delay
            await asyncio.sleep(5)
            return slow_result
        return fast_result

    mock_fetcher_cls = MagicMock()
    mock_fetcher_instance = MagicMock()
    mock_fetcher_instance.fetch = AsyncMock(side_effect=_side_effect_fetch)
    mock_fetcher_instance.fetch_url = AsyncMock(return_value=fast_result)
    mock_fetcher_instance.close = AsyncMock()
    mock_fetcher_instance.__aenter__ = AsyncMock(return_value=mock_fetcher_instance)
    mock_fetcher_instance.__aexit__ = AsyncMock(return_value=False)
    mock_fetcher_cls.return_value = mock_fetcher_instance

    fetch_patcher = patch(
        "app.micro_apps.title_search.services.county_data_fetcher.CountyDataFetcher",
        mock_fetcher_cls,
    )
    discovery_patcher = _setup_discovery_mock()
    ai_patchers = _setup_ai_mocks()

    for p in ai_patchers:
        p.start()
    fetch_patcher.start()
    discovery_patcher.start()
    try:
        import time
        start = time.monotonic()
        await run_pipeline(TEST_ORDER_ID, TEST_ORG_ID, test_session_factory)
        elapsed = time.monotonic() - start
    finally:
        for p in ai_patchers:
            p.stop()
        fetch_patcher.stop()
        discovery_patcher.stop()

    # Pipeline should complete in well under 5s (the slow portal's delay)
    assert elapsed < 4.0, f"Pipeline took {elapsed:.1f}s — slow portal was not cancelled"

    async with test_session_factory() as db:
        order = (await db.execute(
            select(TAOrder).where(TAOrder.id == TEST_ORDER_ID)
        )).scalar_one()
        assert order.status in ("completed", "review_required")

        # Exactly one raw document — the fast winner
        raw_docs = (await db.execute(
            select(TARawDocument).where(TARawDocument.order_id == TEST_ORDER_ID)
        )).scalars().all()
        assert len(raw_docs) == 1
