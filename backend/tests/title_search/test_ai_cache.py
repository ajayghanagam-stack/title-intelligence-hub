"""Tests for TSA AI output caching and replay."""
import json
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.micro_apps.title_search.models.order import TAOrder
from app.micro_apps.title_search.models.document import TADocument
from app.micro_apps.title_search.models.chain_link import TAChainLink
from app.micro_apps.title_search.models.flag import TAFlag
from app.micro_apps.title_search.models.county_source import TACountySource
from app.micro_apps.title_search.pipeline.orchestrator import (
    run_pipeline,
    _serialize_parse_output,
    _serialize_chain_output,
    _replay_parse_cache,
    _replay_chain_cache,
)
from tests.conftest import TEST_ORG_ID, TEST_USER_ID, test_session_factory


@pytest_asyncio.fixture
async def cache_order(db_session: AsyncSession, seed_data):
    """Create an order for cache testing."""
    cs = TACountySource(
        county="Cache", state_code="IL",
        source_type="recorder", availability="digital", is_active=True,
    )
    db_session.add(cs)

    order_id = uuid.uuid4()
    order = TAOrder(
        id=order_id, org_id=TEST_ORG_ID, created_by=TEST_USER_ID,
        property_address="100 Cache St, Cache, IL",
        county="Cache", state_code="IL",
        status="processing", pipeline_stage="order",
    )
    db_session.add(order)
    await db_session.commit()
    return order_id


def test_serialize_parse_roundtrip():
    """Parse serialization produces valid JSON that round-trips."""
    # Create mock ORM-like objects
    class MockDoc:
        def __init__(self, **kw):
            for k, v in kw.items():
                setattr(self, k, v)

    docs = [
        MockDoc(
            doc_type="deed", recording_date="2020-01-15",
            recording_ref="REF-001", grantor={"names": ["A"]},
            grantee={"names": ["B"]}, consideration=250000.0,
            summary="test", confidence=0.92, needs_review=False,
            raw_document_id=uuid.uuid4(),
        ),
    ]
    data = _serialize_parse_output(docs)
    parsed = json.loads(data)
    assert len(parsed) == 1
    assert parsed[0]["doc_type"] == "deed"
    assert parsed[0]["confidence"] == 0.92


def test_serialize_chain_roundtrip():
    """Chain serialization produces valid JSON that round-trips."""
    class MockLink:
        def __init__(self, **kw):
            for k, v in kw.items():
                setattr(self, k, v)

    class MockFlag:
        def __init__(self, **kw):
            for k, v in kw.items():
                setattr(self, k, v)

    links = [MockLink(
        position=1, link_type="conveyance", document_id=uuid.uuid4(),
        from_party={"names": ["A"]}, to_party={"names": ["B"]},
        effective_date="2020-01-15", is_gap=False, gap_description=None,
    )]
    flags = [MockFlag(
        flag_type="unreleased_mortgage", severity="high",
        title="Unreleased", description="desc",
        ai_explanation=None, evidence_refs=[],
        document_id=uuid.uuid4(), chain_link_id=None, status="open",
    )]
    data = _serialize_chain_output(links, flags)
    parsed = json.loads(data)
    assert len(parsed["chain_links"]) == 1
    assert len(parsed["flags"]) == 1
    assert parsed["flags"][0]["severity"] == "high"


@pytest.mark.asyncio
async def test_replay_parse_cache(db_session: AsyncSession, seed_data):
    """Replaying parse cache inserts correct documents."""
    order_id = uuid.uuid4()
    order = TAOrder(
        id=order_id, org_id=TEST_ORG_ID, created_by=TEST_USER_ID,
        property_address="Replay St", county="Test", state_code="IL",
        status="processing",
    )
    db_session.add(order)
    await db_session.flush()

    cached = [
        {
            "doc_type": "deed", "recording_date": "2020-01-15",
            "recording_ref": "REF-001", "grantor": {"names": ["A"]},
            "grantee": {"names": ["B"]}, "consideration": 250000.0,
            "summary": "test", "confidence": 0.92, "needs_review": False,
            "raw_document_id": None,
        },
        {
            "doc_type": "mortgage", "recording_date": "2020-02-01",
            "recording_ref": "REF-002", "grantor": {"names": ["B"]},
            "grantee": {"names": ["Bank"]}, "consideration": 200000.0,
            "summary": "mortgage", "confidence": 0.88, "needs_review": False,
            "raw_document_id": None,
        },
    ]
    await _replay_parse_cache(db_session, TEST_ORG_ID, order_id, cached)
    await db_session.flush()

    docs = (await db_session.execute(
        select(TADocument).where(TADocument.order_id == order_id)
    )).scalars().all()
    assert len(docs) == 2
    assert {d.doc_type for d in docs} == {"deed", "mortgage"}


@pytest.mark.asyncio
async def test_replay_chain_cache(db_session: AsyncSession, seed_data):
    """Replaying chain cache inserts correct links and flags."""
    order_id = uuid.uuid4()
    order = TAOrder(
        id=order_id, org_id=TEST_ORG_ID, created_by=TEST_USER_ID,
        property_address="Replay St", county="Test", state_code="IL",
        status="processing",
    )
    db_session.add(order)
    await db_session.flush()

    cached = {
        "chain_links": [
            {
                "position": 1, "link_type": "conveyance",
                "document_id": None, "from_party": {"names": ["A"]},
                "to_party": {"names": ["B"]}, "effective_date": "2020-01-15",
                "is_gap": False, "gap_description": None,
            },
        ],
        "flags": [
            {
                "flag_type": "unreleased_mortgage", "severity": "high",
                "title": "Unreleased", "description": "desc",
                "document_id": None, "chain_link_id": None, "status": "open",
            },
        ],
    }
    await _replay_chain_cache(db_session, TEST_ORG_ID, order_id, cached)
    await db_session.flush()

    links = (await db_session.execute(
        select(TAChainLink).where(TAChainLink.order_id == order_id)
    )).scalars().all()
    flags = (await db_session.execute(
        select(TAFlag).where(TAFlag.order_id == order_id)
    )).scalars().all()
    assert len(links) == 1
    assert links[0].link_type == "conveyance"
    assert len(flags) == 1
    assert flags[0].severity == "high"


@pytest.mark.asyncio
async def test_parse_stage_cache_hit(cache_order):
    """Running parse stage twice with same raw docs hits cache on second run."""
    from app.micro_apps.title_search.pipeline.orchestrator import STAGE_HANDLERS

    order_id = cache_order

    # First full run — populates cache
    await run_pipeline(order_id, TEST_ORG_ID, test_session_factory)

    async with test_session_factory() as db:
        docs1 = (await db.execute(
            select(TADocument).where(TADocument.order_id == order_id)
        )).scalars().all()
        flags1 = (await db.execute(
            select(TAFlag).where(TAFlag.order_id == order_id)
        )).scalars().all()

    doc_types_1 = sorted(d.doc_type for d in docs1)
    flag_types_1 = sorted(f.flag_type for f in flags1)
    doc_count_1 = len(docs1)

    assert doc_count_1 >= 1  # sanity

    # Re-run parse and chain stages directly — should hit cache
    async with test_session_factory() as db:
        await STAGE_HANDLERS["parse"](order_id, TEST_ORG_ID, db)
        await db.commit()

    async with test_session_factory() as db:
        await STAGE_HANDLERS["chain"](order_id, TEST_ORG_ID, db)
        await db.commit()

    async with test_session_factory() as db:
        docs2 = (await db.execute(
            select(TADocument).where(TADocument.order_id == order_id)
        )).scalars().all()
        flags2 = (await db.execute(
            select(TAFlag).where(TAFlag.order_id == order_id)
        )).scalars().all()

    doc_types_2 = sorted(d.doc_type for d in docs2)
    flag_types_2 = sorted(f.flag_type for f in flags2)

    # Same doc types and flag types after cache replay
    assert doc_types_2 == doc_types_1
    assert flag_types_2 == flag_types_1
    assert len(docs2) == doc_count_1
