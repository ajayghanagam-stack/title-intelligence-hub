"""E2E test: create order with new fields → run pipeline → verify PDF report."""
import uuid
from datetime import date
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.micro_apps.title_search.models.order import TAOrder
from app.micro_apps.title_search.models.county_source import TACountySource
from app.micro_apps.title_search.models.document import TADocument
from app.micro_apps.title_search.models.package import TAPackage
from app.micro_apps.title_search.pipeline.orchestrator import run_pipeline
from app.micro_apps.title_search.services.package_service import generate_package_pdf
from app.micro_apps.title_search.services.county_data_fetcher import FetchResult
from tests.conftest import TEST_ORG_ID, TEST_USER_ID, test_session_factory


SAMPLE_HTML = "<html><body><h1>Property Record</h1><table><tr><td>Owner: Derrick R. Pitts</td></tr></table></body></html>"

SAMPLE_EXTRACTION_RESULT = {
    "property_info": {
        "owner_name": "Derrick R. Pitts",
        "address": "870 Friendship Cir, Jacksonville, FL 32210",
        "municipality": "Jacksonville",
        "zip": "32210",
        "parcel_number": "012875-1145",
        "subdivision": "Blue Lake Estates Unit 2",
        "legal_description": "Lot 40, Blue Lake Estates Unit 2, according to the plat thereof recorded in Plat Book 65, Pages 138-145.",
    },
    "deeds": [
        {
            "doc_type": "deed",
            "deed_type_detail": "Warranty Deed",
            "recording_date": "2017-02-23",
            "recording_ref": "2017043190",
            "book_page": "17887/1785",
            "instrument_number": "2017043190",
            "grantor": "D.R. Horton, Inc - Jacksonville, a Delaware Corporation",
            "grantee": "Derrick R. Pitts, a married man",
            "consideration": 10.00,
        },
    ],
    "mortgages": [
        {
            "borrower": "Derrick R. Pitts and Norma D. Pitts, husband and wife",
            "lender": "Mortgage Electronic Registration Systems, Inc., as nominee for DHI Mortgage Company, Ltd.",
            "trustee": "NA",
            "recording_date": "2017-02-23",
            "recording_ref": "2017043193",
            "book_page": "17887/1792",
            "instrument_number": "2017043193",
            "loan_amount": 264557.00,
            "maturity_date": "2047-03-01",
            "open_closed_end": "Closed End",
            "min_number": "10002041000377848",
            "riders": "PUD Rider\nVA Rider",
        },
        {
            "borrower": "Derrick R. Pitts, a married person and Norma D. Pitts, their spouse",
            "lender": "Mortgage Electronic Registration Systems, Inc., as nominee for Rocket Mortgage, LLC",
            "trustee": "N/A",
            "recording_date": "2025-12-16",
            "recording_ref": "2025286372",
            "book_page": "21725/1928",
            "instrument_number": "2025286372",
            "loan_amount": 95940.00,
            "maturity_date": "2056-01-01",
            "open_closed_end": "Closed End",
            "min_number": "100039035755507661",
            "riders": "PUD Rider",
        },
    ],
    "liens": [],
    "tax_info": {
        "parcel_id": "012875-1145",
        "assessment_year": "2025",
        "land_value": 75000,
        "improvement_value": 316818,
        "total_value": 391818,
        "tax_amount": 4237.86,
        "tax_status": "Paid",
        "homestead_exemption": True,
    },
    "misc_documents": [
        {"description": "Plat Map is Recorded in B/P 65/138"},
    ],
    "confidence": 0.92,
}


def _mock_analysis_return(documents: list[dict]) -> dict:
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


def _setup_mocks():
    mock_extractor_cls = MagicMock()
    mock_extractor_instance = AsyncMock()
    mock_extractor_instance.extract_all = AsyncMock(return_value=SAMPLE_EXTRACTION_RESULT)
    mock_extractor_cls.return_value = mock_extractor_instance

    mock_analysis_cls = MagicMock()
    mock_analysis_instance = AsyncMock()
    mock_analysis_instance.analyze = AsyncMock(side_effect=_mock_analysis_return)
    mock_analysis_cls.return_value = mock_analysis_instance

    fetch_result = FetchResult(
        content=SAMPLE_HTML,
        content_format="html",
        source_url="https://beacon.schneidercorp.com/test",
        success=True,
    )
    mock_fetcher_cls = MagicMock()
    mock_fetcher_instance = MagicMock()
    mock_fetcher_instance.fetch = AsyncMock(return_value=fetch_result)
    mock_fetcher_instance.close = AsyncMock()
    mock_fetcher_instance.__aenter__ = AsyncMock(return_value=mock_fetcher_instance)
    mock_fetcher_instance.__aexit__ = AsyncMock(return_value=False)
    mock_fetcher_cls.return_value = mock_fetcher_instance

    patchers = [
        patch(
            "app.micro_apps.title_search.ai.property_data_extractor.PropertyDataExtractorAgent",
            mock_extractor_cls,
        ),
        patch(
            "app.micro_apps.title_search.ai.chain_analysis_agent.ChainAnalysisAgent",
            mock_analysis_cls,
        ),
        patch(
            "app.micro_apps.title_search.services.county_data_fetcher.CountyDataFetcher",
            mock_fetcher_cls,
        ),
    ]
    return patchers


@pytest_asyncio.fixture
async def order_with_new_fields(db_session: AsyncSession, seed_data):
    """Create an order with all new form fields + a Hendry county source."""
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
        org_id=TEST_ORG_ID,
        created_by=TEST_USER_ID,
        property_address="870 Friendship Cir",
        city="Jacksonville",
        zip_code="32210",
        county="Hendry",
        state_code="FL",
        borrower_name="Derrick R. Pitts",
        parcel_number="012875-1145",
        search_scope="current_owner",
        search_years=60,
        order_reference="Test",
        effective_date=date(2026, 3, 28),
        status="processing",
        pipeline_stage="order",
    )
    db_session.add(order)
    await db_session.commit()
    return order


@pytest.mark.asyncio
async def test_pipeline_and_report_with_new_fields(order_with_new_fields):
    """Full pipeline → PDF report with borrower_name, city, zip, order_reference, effective_date."""
    order_id = order_with_new_fields.id
    patchers = _setup_mocks()

    for p in patchers:
        p.start()
    try:
        await run_pipeline(order_id, TEST_ORG_ID, test_session_factory)
    finally:
        for p in patchers:
            p.stop()

    async with test_session_factory() as db:
        # Verify order completed
        order = (await db.execute(
            select(TAOrder).where(TAOrder.id == order_id)
        )).scalar_one()
        assert order.status in ("completed", "review_required"), f"Unexpected status: {order.status}"
        print(f"\n  Pipeline status: {order.status}")
        print(f"  Pipeline stage: {order.pipeline_stage}")

        # Verify new fields survived pipeline
        assert order.borrower_name == "Derrick R. Pitts"
        assert order.city == "Jacksonville"
        assert order.zip_code == "32210"
        assert order.order_reference == "Test"
        assert str(order.effective_date) == "2026-03-28"
        print("  New fields intact after pipeline: OK")

        # Verify documents were parsed
        docs = (await db.execute(
            select(TADocument).where(TADocument.order_id == order_id)
        )).scalars().all()
        print(f"  Documents: {len(docs)} ({', '.join(d.doc_type for d in docs)})")
        assert len(docs) >= 2

        # Verify package was created
        pkg = (await db.execute(
            select(TAPackage).where(TAPackage.order_id == order_id)
        )).scalar_one_or_none()
        assert pkg is not None, "Package should exist"
        print(f"  Package: {pkg.package_number} (status={pkg.status})")

        # Generate PDF report
        pdf_bytes = await generate_package_pdf(db, TEST_ORG_ID, order_id)
        assert len(pdf_bytes) > 0, "PDF should not be empty"
        print(f"  PDF size: {len(pdf_bytes):,} bytes")

        # Extract text from PDF using PyMuPDF
        import fitz
        pdf_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        num_pages = len(pdf_doc)
        pdf_text = ""
        for page in pdf_doc:
            pdf_text += page.get_text()
        pdf_doc.close()
        print(f"  PDF pages: {num_pages}")

        # Check new fields appear in PDF
        checks = {
            "Borrower name": "Derrick R. Pitts",
            "City/Municipality": "Jacksonville",
            "ZIP code": "32210",
            "Order reference": "Test",
            "Effective date": "03/28/2026",
            "Searched from date": "03/28/1966",  # 2026 - 60 years
            "Product type": "Current Owner",
            "Parcel number": "012875-1145",
            "County": "Hendry",
        }

        all_ok = True
        for label, expected in checks.items():
            if expected in pdf_text:
                print(f"  PDF contains {label}: '{expected}'")
            else:
                print(f"  PDF MISSING {label}: '{expected}'")
                all_ok = False

        if not all_ok:
            # Dump first 2000 chars of extracted text for debugging
            print(f"\n  --- PDF text (first 2000 chars) ---")
            print(pdf_text[:2000])
            print("  ---")

        assert all_ok, "Some expected fields are missing from the PDF report"
        print("\n  All PDF content checks passed!")
