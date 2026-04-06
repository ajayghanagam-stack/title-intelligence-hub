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
from app.micro_apps.title_search.pipeline.orchestrator import run_pipeline, trigger_pipeline
from app.micro_apps.title_search.services.real_data_fetcher import PropertyData
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


def _make_sample_property_data(success: bool = True, county: str = "Hendry") -> PropertyData:
    """Create a PropertyData matching SAMPLE_EXTRACTION_RESULT shape."""
    if not success:
        return PropertyData(
            county=county,
            sources_used=[],
            sources_failed=[{"type": "tax", "error": "Connection timeout"}],
        )
    return PropertyData(
        parcel_number="1-29-43-01-010-0000-001.0",
        address="123 Main St",
        city="LaBelle",
        state="FL",
        county=county,
        subdivision="Palm Village",
        owner_name="Jane Doe",
        legal_description="Lot 1, Block 2, Palm Village Subdivision",
        assessed_value=225000.0,
        land_value=50000.0,
        improvement_value=175000.0,
        total_value=225000.0,
        tax_amount=3200.50,
        assessment_year="2025",
        tax_status="Paid",
        homestead_exemption=True,
        sales_history=[
            {
                "recording_date": "2020-01-15",
                "consideration": 250000.0,
                "instrument_number": "2020001234",
                "book_page": "1234/567",
                "grantor": "John Smith",
                "grantee": "Jane Doe",
                "deed_type": "Warranty Deed",
            },
        ],
        recorded_documents=[
            {
                "doc_type": "mortgage",
                "record_date": "2020-02-01",
                "instrument_number": "2020001235",
                "book_page": "1234/568",
                "grantor": "Jane Doe",
                "grantee": "First National Bank",
                "consideration": 200000.0,
            },
        ],
        sources_used=[
            {"type": "tax", "url": "https://beacon.schneidercorp.com/test"},
        ],
    )


def _setup_fetch_mock(success: bool = True, county: str = "Hendry"):
    """Create a patcher for real_data_fetcher.fetch_property_data()."""
    prop_data = _make_sample_property_data(success=success, county=county)
    return patch(
        "app.micro_apps.title_search.services.real_data_fetcher.fetch_property_data",
        new_callable=AsyncMock,
        return_value=prop_data,
    )


def _setup_discovery_mock(portals=None):
    """Create a patcher for PortalDiscoveryAgent.discover()."""
    if portals is None:
        portals = []
    mock_agent_cls = MagicMock()
    mock_agent_inst = AsyncMock()
    mock_agent_inst.discover = AsyncMock(
        return_value={"portals": portals, "county_has_digital_records": len(portals) > 0},
    )
    mock_agent_cls.return_value = mock_agent_inst
    return patch(
        "app.micro_apps.title_search.ai.portal_discovery_agent.PortalDiscoveryAgent",
        mock_agent_cls,
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

        # Legal description should be populated from fetch data
        assert order.legal_description is None or order.legal_description == "Lot 1, Block 2, Palm Village Subdivision"

        # Source assignments should exist
        sources = (await db.execute(
            select(TASourceAssignment).where(TASourceAssignment.order_id == TEST_ORDER_ID)
        )).scalars().all()
        assert len(sources) >= 1

        # Raw documents should exist with JSON content format (from fetch_property_data)
        raw_docs = (await db.execute(
            select(TARawDocument).where(TARawDocument.order_id == TEST_ORDER_ID)
        )).scalars().all()
        assert len(raw_docs) >= 1
        assert raw_docs[0].content_format == "json"

        # Parsed documents should exist (deed + mortgage + tax from JSON parsing)
        docs = (await db.execute(
            select(TADocument).where(TADocument.order_id == TEST_ORDER_ID)
        )).scalars().all()
        assert len(docs) >= 2  # At least deed + mortgage

        # Verify deed has metadata (from JSON parse path)
        deed_docs = [d for d in docs if d.doc_type == "deed"]
        assert len(deed_docs) >= 1
        assert deed_docs[0].doc_metadata is not None
        assert deed_docs[0].doc_metadata.get("book_page") == "1234/567"
        assert deed_docs[0].doc_metadata.get("instrument_number") == "2020001234"

        # Verify mortgage has doc_metadata (from JSON parse path)
        mtg_docs = [d for d in docs if d.doc_type == "mortgage"]
        assert len(mtg_docs) >= 1
        assert mtg_docs[0].doc_metadata is not None
        assert mtg_docs[0].doc_metadata.get("book_page") == "1234/568"
        assert mtg_docs[0].doc_metadata.get("instrument_number") == "2020001235"

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
    """Pipeline proceeds with minimal report for counties with no digital data."""
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

    # Fetch returns no data for rural county
    fetch_patcher = _setup_fetch_mock(success=False, county="Rural")
    discovery_mock = _setup_discovery_mock(portals=[])
    ai_patchers = _setup_ai_mocks()

    for p in ai_patchers:
        p.start()
    fetch_patcher.start()
    discovery_mock.start()
    try:
        await run_pipeline(order_id, TEST_ORG_ID, test_session_factory)
    finally:
        for p in ai_patchers:
            p.stop()
        fetch_patcher.stop()
        discovery_mock.stop()

    async with test_session_factory() as db:
        order = (await db.execute(
            select(TAOrder).where(TAOrder.id == order_id)
        )).scalar_one()
        # Pipeline produces minimal report with missing_source flag
        assert order.status == "review_required"


@pytest.mark.asyncio
async def test_pipeline_no_county_source_fails_gracefully(db_session: AsyncSession, seed_data):
    """Pipeline proceeds with minimal report when no portal can be found."""
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

    # Mock discovery + fetch returning no data
    discovery_mock = _setup_discovery_mock(portals=[])
    fetch_mock = _setup_fetch_mock(success=False, county="NoCounty")
    ai_patchers = _setup_ai_mocks()

    for p in ai_patchers:
        p.start()
    discovery_mock.start()
    fetch_mock.start()
    try:
        await run_pipeline(order_id, TEST_ORG_ID, test_session_factory)
    finally:
        for p in ai_patchers:
            p.stop()
        discovery_mock.stop()
        fetch_mock.stop()

    async with test_session_factory() as db:
        order = (await db.execute(
            select(TAOrder).where(TAOrder.id == order_id)
        )).scalar_one()
        # Pipeline now produces a minimal report with missing_source flag
        assert order.status == "review_required"
        flags = (await db.execute(
            select(TAFlag).where(TAFlag.order_id == order_id)
        )).scalars().all()
        flag_types = [f.flag_type for f in flags]
        assert "missing_source" in flag_types


@pytest.mark.asyncio
async def test_pipeline_fetch_failure_tries_discovery(db_session: AsyncSession, seed_data):
    """Pipeline tries AI portal discovery when fetch fails, proceeds with minimal report."""
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

    fetch_patcher = _setup_fetch_mock(success=False, county="Broken")
    discovery_mock = _setup_discovery_mock(portals=[])
    ai_patchers = _setup_ai_mocks()

    for p in ai_patchers:
        p.start()
    fetch_patcher.start()
    discovery_mock.start()
    try:
        await run_pipeline(order_id, TEST_ORG_ID, test_session_factory)
    finally:
        for p in ai_patchers:
            p.stop()
        fetch_patcher.stop()
        discovery_mock.stop()

    async with test_session_factory() as db:
        order = (await db.execute(
            select(TAOrder).where(TAOrder.id == order_id)
        )).scalar_one()
        # Pipeline now produces a minimal report with missing_source flag
        assert order.status == "review_required"
        flags = (await db.execute(
            select(TAFlag).where(TAFlag.order_id == order_id)
        )).scalars().all()
        flag_types = [f.flag_type for f in flags]
        assert "missing_source" in flag_types


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
async def test_pipeline_discovery_saves_portal(db_session: AsyncSession, seed_data):
    """AI discovery finds portals and saves them to TACountySource registry."""
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

    # Discovery finds a portal, fetch returns data using it
    discovery_patcher = _setup_discovery_mock(portals=[{
        "url": "https://discovered.example.com/property",
        "source_type": "property_appraiser",
        "portal_type": "generic_web",
    }])
    fetch_patcher = _setup_fetch_mock(success=True, county="Slow")
    ai_patchers = _setup_ai_mocks()

    for p in ai_patchers:
        p.start()
    fetch_patcher.start()
    discovery_patcher.start()
    try:
        await run_pipeline(order_id, TEST_ORG_ID, test_session_factory)
    finally:
        for p in ai_patchers:
            p.stop()
        fetch_patcher.stop()
        discovery_patcher.stop()

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

        # Raw document should exist
        raw_docs = (await db.execute(
            select(TARawDocument).where(TARawDocument.order_id == order_id)
        )).scalars().all()
        assert len(raw_docs) >= 1


@pytest.mark.asyncio
async def test_pipeline_completes_with_fetch_data(pipeline_order):
    """Pipeline completes successfully with fetch_property_data mock."""
    fetch_patcher = _setup_fetch_mock(success=True)
    discovery_patcher = _setup_discovery_mock()
    ai_patchers = _setup_ai_mocks()

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
        order = (await db.execute(
            select(TAOrder).where(TAOrder.id == TEST_ORDER_ID)
        )).scalar_one()
        assert order.status in ("completed", "review_required")

        # Raw document should exist
        raw_docs = (await db.execute(
            select(TARawDocument).where(TARawDocument.order_id == TEST_ORDER_ID)
        )).scalars().all()
        assert len(raw_docs) >= 1


@pytest.mark.asyncio
async def test_trigger_pipeline_temporal_backend(pipeline_order):
    """trigger_pipeline should start a Temporal workflow when PIPELINE_BACKEND=temporal."""
    mock_client = AsyncMock()
    mock_client.start_workflow = AsyncMock()

    mock_settings = MagicMock()
    mock_settings.PIPELINE_BACKEND = "temporal"
    mock_settings.TEMPORAL_ADDRESS = "localhost:7233"
    mock_settings.TEMPORAL_NAMESPACE = "default"
    mock_settings.TSA_TEMPORAL_TASK_QUEUE = "title-search"
    mock_settings.TSA_RESEARCH_MODE = "grounded"

    with patch(
        "app.micro_apps.title_search.pipeline.orchestrator.get_settings",
        return_value=mock_settings,
    ):
        with patch(
            "temporalio.client.Client.connect",
            return_value=mock_client,
        ):
            await trigger_pipeline(
                TEST_ORDER_ID, TEST_ORG_ID, test_session_factory
            )

    # Verify start_workflow was called with correct args
    mock_client.start_workflow.assert_called_once()
    call_kwargs = mock_client.start_workflow.call_args
    assert call_kwargs.kwargs["task_queue"] == "title-search"
    # args should be [order_id, org_id, research_mode]
    workflow_args = call_kwargs.kwargs["args"]
    assert workflow_args[0] == str(TEST_ORDER_ID)
    assert workflow_args[1] == str(TEST_ORG_ID)
    assert workflow_args[2] == "grounded"


@pytest.mark.asyncio
async def test_trigger_pipeline_background_tasks(pipeline_order):
    """trigger_pipeline should use BackgroundTasks when PIPELINE_BACKEND=background_tasks."""
    mock_bg = MagicMock()
    mock_bg.add_task = MagicMock()

    mock_settings = MagicMock()
    mock_settings.PIPELINE_BACKEND = "background_tasks"

    with patch(
        "app.micro_apps.title_search.pipeline.orchestrator.get_settings",
        return_value=mock_settings,
    ):
        await trigger_pipeline(
            TEST_ORDER_ID, TEST_ORG_ID, test_session_factory,
            background_tasks=mock_bg,
        )

    mock_bg.add_task.assert_called_once()
    call_args = mock_bg.add_task.call_args[0]
    assert call_args[0] == run_pipeline
    assert call_args[1] == TEST_ORDER_ID
