import uuid
from datetime import datetime, timezone

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.micro_apps.title_search.models.order import TAOrder
from app.micro_apps.title_search.models.source_assignment import TASourceAssignment
from app.micro_apps.title_search.models.raw_document import TARawDocument
from app.micro_apps.title_search.models.document import TADocument
from app.micro_apps.title_search.models.chain_link import TAChainLink
from app.micro_apps.title_search.models.flag import TAFlag
from app.micro_apps.title_search.models.review import TAReview
from app.micro_apps.title_search.models.package import TAPackage
from app.micro_apps.title_search.models.county_source import TACountySource
from app.models.micro_app import MicroApp
from app.models.subscription import Subscription

from tests.conftest import TEST_ORG_ID, TEST_USER_ID, TEST_APP_ID

# TSA-specific test UUIDs
TEST_TS_APP_ID = uuid.UUID("00000000-0000-0000-0000-000000002000")
TEST_ORDER_ID = uuid.UUID("00000000-0000-0000-0000-000000100000")
TEST_SOURCE_ASSIGNMENT_ID = uuid.UUID("00000000-0000-0000-0000-000000200000")
TEST_RAW_DOC_ID = uuid.UUID("00000000-0000-0000-0000-000000300000")
TEST_DOCUMENT_ID = uuid.UUID("00000000-0000-0000-0000-000000400000")
TEST_CHAIN_LINK_ID = uuid.UUID("00000000-0000-0000-0000-000000500000")
TEST_FLAG_ID = uuid.UUID("00000000-0000-0000-0000-000000600000")
TEST_COUNTY_SOURCE_ID = uuid.UUID("00000000-0000-0000-0000-000000700000")


@pytest_asyncio.fixture
async def ts_app_and_subscription(db_session: AsyncSession, seed_data):
    """Create TSA micro app and active subscription."""
    ts_app = MicroApp(
        id=TEST_TS_APP_ID,
        name="Title Search & Abstracting",
        slug="title-search",
        description="Automated county record searches",
        icon="search",
    )
    db_session.add(ts_app)

    sub = Subscription(
        org_id=TEST_ORG_ID,
        app_id=TEST_TS_APP_ID,
        status="active",
        purchased_at=datetime.now(timezone.utc),
        enabled_at=datetime.now(timezone.utc),
    )
    db_session.add(sub)
    await db_session.commit()
    return ts_app


@pytest_asyncio.fixture
async def sample_order(db_session: AsyncSession, ts_app_and_subscription):
    """Create a sample order."""
    order = TAOrder(
        id=TEST_ORDER_ID,
        org_id=TEST_ORG_ID,
        created_by=TEST_USER_ID,
        property_address="123 Main St, Springfield, IL 62701",
        county="Sangamon",
        state_code="IL",
        search_scope="full",
        search_years=60,
        status="pending",
    )
    db_session.add(order)
    await db_session.commit()
    return order


@pytest_asyncio.fixture
async def sample_order_with_data(db_session: AsyncSession, sample_order):
    """Create a sample order with source assignments, documents, chain links, and flags."""
    source = TASourceAssignment(
        id=TEST_SOURCE_ASSIGNMENT_ID,
        org_id=TEST_ORG_ID,
        order_id=TEST_ORDER_ID,
        source_type="recorder",
        availability="digital",
        status="completed",
    )
    db_session.add(source)

    raw_doc = TARawDocument(
        id=TEST_RAW_DOC_ID,
        org_id=TEST_ORG_ID,
        order_id=TEST_ORDER_ID,
        source_assignment_id=TEST_SOURCE_ASSIGNMENT_ID,
        document_ref="2020-001234",
        raw_content="<html>Warranty Deed...</html>",
        content_format="html",
    )
    db_session.add(raw_doc)

    doc = TADocument(
        id=TEST_DOCUMENT_ID,
        org_id=TEST_ORG_ID,
        order_id=TEST_ORDER_ID,
        raw_document_id=TEST_RAW_DOC_ID,
        doc_type="deed",
        recording_date="2020-01-15",
        recording_ref="2020-001234",
        grantor={"names": ["John Smith"], "entity_type": "individual"},
        grantee={"names": ["Jane Doe"], "entity_type": "individual"},
        consideration=250000.00,
        confidence=0.95,
        needs_review=False,
    )
    db_session.add(doc)

    chain_link = TAChainLink(
        id=TEST_CHAIN_LINK_ID,
        org_id=TEST_ORG_ID,
        order_id=TEST_ORDER_ID,
        document_id=TEST_DOCUMENT_ID,
        position=1,
        link_type="conveyance",
        from_party={"names": ["John Smith"]},
        to_party={"names": ["Jane Doe"]},
        effective_date="2020-01-15",
        is_gap=False,
    )
    db_session.add(chain_link)

    flag = TAFlag(
        id=TEST_FLAG_ID,
        org_id=TEST_ORG_ID,
        order_id=TEST_ORDER_ID,
        document_id=TEST_DOCUMENT_ID,
        flag_type="unreleased_mortgage",
        severity="high",
        title="Unreleased Mortgage",
        description="Mortgage recorded 2020-01-15 has no corresponding satisfaction.",
    )
    db_session.add(flag)

    await db_session.commit()
    return sample_order
