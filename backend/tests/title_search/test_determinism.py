"""Golden-set / regression tests for deterministic TSA pipeline outputs.

Tests the deterministic layers (flag detection rules, severity clamping,
normalization, cache serialization, and pipeline output) with fixed inputs
and hardcoded expected outputs. These tests MUST pass before any version
bump of prompts, models, tool schemas, or rule sets.
"""

from __future__ import annotations

import copy
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
from app.micro_apps.title_search.services.flag_rules import (
    RULES_VERSION,
    VALID_FLAG_TYPES,
    VALID_SEVERITIES,
    SEVERITY_FLOOR,
    SEVERITY_CAP,
    LOW_CONFIDENCE_THRESHOLD,
    detect_unreleased_mortgages,
    detect_low_confidence,
    detect_all_flags,
    normalize_flags,
)
from app.micro_apps.title_search.pipeline.orchestrator import (
    run_pipeline,
    STAGE_HANDLERS,
    _serialize_parse_output,
    _serialize_chain_output,
)
from tests.conftest import TEST_ORG_ID, TEST_USER_ID, test_session_factory

# ---------------------------------------------------------------------------
# Golden inputs — fixed document sets representing real title search scenarios
# ---------------------------------------------------------------------------

GOLDEN_DOCUMENTS = [
    {
        "id": uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001"),
        "doc_type": "deed",
        "recording_date": "2015-03-20",
        "recording_ref": "2015-001234",
        "grantor": {"names": ["Robert Johnson"], "entity_type": "individual"},
        "grantee": {"names": ["Sarah Williams"], "entity_type": "individual"},
        "consideration": 325000.00,
        "summary": "Warranty deed transferring property",
        "confidence": 0.94,
    },
    {
        "id": uuid.UUID("aaaaaaaa-0000-0000-0000-000000000002"),
        "doc_type": "mortgage",
        "recording_date": "2015-03-20",
        "recording_ref": "2015-001235",
        "grantor": {"names": ["Sarah Williams"], "entity_type": "individual"},
        "grantee": {"names": ["First National Bank"], "entity_type": "corporation"},
        "consideration": 260000.00,
        "summary": "Mortgage on property",
        "confidence": 0.91,
    },
    {
        "id": uuid.UUID("aaaaaaaa-0000-0000-0000-000000000003"),
        "doc_type": "deed",
        "recording_date": "2020-06-15",
        "recording_ref": "2020-005678",
        "grantor": {"names": ["Sarah Williams"], "entity_type": "individual"},
        "grantee": {"names": ["Michael Chen"], "entity_type": "individual"},
        "consideration": 410000.00,
        "summary": "Warranty deed transferring property",
        "confidence": 0.96,
    },
    {
        "id": uuid.UUID("aaaaaaaa-0000-0000-0000-000000000004"),
        "doc_type": "mortgage",
        "recording_date": "2020-06-15",
        "recording_ref": "2020-005679",
        "grantor": {"names": ["Michael Chen"], "entity_type": "individual"},
        "grantee": {"names": ["Pacific Savings Bank"], "entity_type": "corporation"},
        "consideration": 350000.00,
        "summary": "Mortgage on property",
        "confidence": 0.89,
    },
    {
        "id": uuid.UUID("aaaaaaaa-0000-0000-0000-000000000005"),
        "doc_type": "easement",
        "recording_date": "2018-09-01",
        "recording_ref": "2018-003456",
        "grantor": {"names": ["Sarah Williams"], "entity_type": "individual"},
        "grantee": {"names": ["City Water Authority"], "entity_type": "government"},
        "consideration": None,
        "summary": "Utility easement for water main",
        "confidence": 0.60,  # Below threshold — should trigger low_confidence flag
    },
]

# A document with a satisfaction that matches the first mortgage
GOLDEN_SATISFACTION = {
    "id": uuid.UUID("aaaaaaaa-0000-0000-0000-000000000006"),
    "doc_type": "satisfaction",
    "recording_date": "2020-06-14",
    "recording_ref": "2015-001235",  # Matches first mortgage
    "grantor": {"names": ["First National Bank"], "entity_type": "corporation"},
    "grantee": {"names": ["Sarah Williams"], "entity_type": "individual"},
    "consideration": None,
    "summary": "Satisfaction of mortgage",
    "confidence": 0.93,
}

# ---------------------------------------------------------------------------
# Golden expected outputs
# ---------------------------------------------------------------------------

# Without satisfaction: 2 unreleased mortgages + 1 low confidence = 3 flags
GOLDEN_FLAGS_NO_SATISFACTION = [
    # Sorted by: severity (high first), then flag_type, then description
    {
        "flag_type": "unreleased_mortgage",
        "severity": "high",
        "title": "Unreleased Mortgage",
    },
    {
        "flag_type": "unreleased_mortgage",
        "severity": "high",
        "title": "Unreleased Mortgage",
    },
    {
        "flag_type": "low_confidence",
        "severity": "medium",
        "title": "Low Confidence Parse",
    },
]

# With satisfaction: 1 unreleased mortgage (second one) + 1 low confidence = 2 flags
GOLDEN_FLAGS_WITH_SATISFACTION = [
    {
        "flag_type": "unreleased_mortgage",
        "severity": "high",
        "title": "Unreleased Mortgage",
    },
    {
        "flag_type": "low_confidence",
        "severity": "medium",
        "title": "Low Confidence Parse",
    },
]


class MockDoc:
    """Lightweight ORM-like object for golden set testing."""
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


def _docs_from_golden(golden_list):
    """Create MockDoc objects from golden dict list."""
    return [MockDoc(**d) for d in golden_list]


# ---------------------------------------------------------------------------
# Determinism tests — same inputs → identical outputs across N runs
# ---------------------------------------------------------------------------

def test_flag_detection_deterministic_10_runs():
    """Run detect_all_flags 10x with same inputs — all results must be identical."""
    docs = _docs_from_golden(GOLDEN_DOCUMENTS)
    results = []
    for _ in range(10):
        flags = detect_all_flags(docs)
        results.append(flags)

    first = results[0]
    for r in results[1:]:
        assert len(r) == len(first)
        for f1, f2 in zip(first, r):
            assert f1["flag_type"] == f2["flag_type"]
            assert f1["severity"] == f2["severity"]
            assert f1["title"] == f2["title"]
            assert f1["description"] == f2["description"]
            assert f1.get("document_id") == f2.get("document_id")


def test_flag_normalization_deterministic_10_runs():
    """Normalize the same raw flags 10x — all results must be identical."""
    raw_flags = [
        {"flag_type": "unreleased_mortgage", "severity": "high",
         "title": "Unreleased", "description": "Mortgage REF-001 unreleased",
         "document_id": uuid.UUID("aaaaaaaa-0000-0000-0000-000000000002")},
        {"flag_type": "low_confidence", "severity": "critical",  # Will be capped to medium
         "title": "Low Conf", "description": "Low conf doc",
         "document_id": uuid.UUID("aaaaaaaa-0000-0000-0000-000000000005")},
        {"flag_type": "chain_gap", "severity": "low",  # Will be floored to high
         "title": "Gap", "description": "Gap in chain",
         "document_id": None},
    ]
    results = []
    for _ in range(10):
        r = normalize_flags(copy.deepcopy(raw_flags))
        results.append(r)

    first = results[0]
    for r in results[1:]:
        assert len(r) == len(first)
        for f1, f2 in zip(first, r):
            assert f1["flag_type"] == f2["flag_type"]
            assert f1["severity"] == f2["severity"]


# ---------------------------------------------------------------------------
# Snapshot tests — exact expected values
# ---------------------------------------------------------------------------

def test_flag_detection_snapshot_no_satisfaction():
    """Assert exact flag output for golden documents without satisfaction."""
    docs = _docs_from_golden(GOLDEN_DOCUMENTS)
    flags = detect_all_flags(docs)

    # 2 unreleased mortgages (neither has satisfaction) + 1 low confidence (easement at 0.60)
    assert len(flags) == 3

    # All flags match golden expected output
    for i, expected in enumerate(GOLDEN_FLAGS_NO_SATISFACTION):
        assert flags[i]["flag_type"] == expected["flag_type"], f"Flag {i} type mismatch"
        assert flags[i]["severity"] == expected["severity"], f"Flag {i} severity mismatch"
        assert flags[i]["title"] == expected["title"], f"Flag {i} title mismatch"

    # High severity flags come before medium
    assert flags[0]["severity"] == "high"
    assert flags[1]["severity"] == "high"
    assert flags[2]["severity"] == "medium"


def test_flag_detection_snapshot_with_satisfaction():
    """Adding a satisfaction removes one unreleased mortgage flag."""
    all_docs = GOLDEN_DOCUMENTS + [GOLDEN_SATISFACTION]
    docs = _docs_from_golden(all_docs)
    flags = detect_all_flags(docs)

    # 1 unreleased mortgage (second one, ref 2020-005679) + 1 low confidence = 2 flags
    assert len(flags) == 2

    for i, expected in enumerate(GOLDEN_FLAGS_WITH_SATISFACTION):
        assert flags[i]["flag_type"] == expected["flag_type"], f"Flag {i} type mismatch"
        assert flags[i]["severity"] == expected["severity"], f"Flag {i} severity mismatch"


def test_severity_clamping_snapshot():
    """Assert exact severity clamping for each floor/cap rule.

    Each flag has a unique document_id to prevent deduplication from merging them.
    """
    raw_flags = [
        # chain_gap floor=high: low → high
        {"flag_type": "chain_gap", "severity": "low", "title": "G", "description": "D1",
         "document_id": uuid.UUID("bbbbbbbb-0000-0000-0000-000000000001")},
        # chain_gap floor=high: medium → high
        {"flag_type": "chain_gap", "severity": "medium", "title": "G", "description": "D2",
         "document_id": uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")},
        # chain_gap floor=high: critical stays critical
        {"flag_type": "chain_gap", "severity": "critical", "title": "G", "description": "D3",
         "document_id": uuid.UUID("bbbbbbbb-0000-0000-0000-000000000003")},
        # unreleased_mortgage floor=high: medium → high
        {"flag_type": "unreleased_mortgage", "severity": "medium", "title": "U", "description": "D4",
         "document_id": uuid.UUID("bbbbbbbb-0000-0000-0000-000000000004")},
        # low_confidence cap=medium: critical → medium
        {"flag_type": "low_confidence", "severity": "critical", "title": "L", "description": "D5",
         "document_id": uuid.UUID("bbbbbbbb-0000-0000-0000-000000000005")},
        # low_confidence cap=medium: high → medium
        {"flag_type": "low_confidence", "severity": "high", "title": "L", "description": "D6",
         "document_id": uuid.UUID("bbbbbbbb-0000-0000-0000-000000000006")},
        # low_confidence cap=medium: low stays low
        {"flag_type": "low_confidence", "severity": "low", "title": "L", "description": "D7",
         "document_id": uuid.UUID("bbbbbbbb-0000-0000-0000-000000000007")},
        # missing_source cap=medium: high → medium
        {"flag_type": "missing_source", "severity": "high", "title": "M", "description": "D8",
         "document_id": uuid.UUID("bbbbbbbb-0000-0000-0000-000000000008")},
    ]
    result = normalize_flags(raw_flags)

    expected_severities = {
        "D1": "high",    # chain_gap low → high (floor)
        "D2": "high",    # chain_gap medium → high (floor)
        "D3": "critical", # chain_gap critical stays
        "D4": "high",    # unreleased_mortgage medium → high (floor)
        "D5": "medium",  # low_confidence critical → medium (cap)
        "D6": "medium",  # low_confidence high → medium (cap)
        "D7": "low",     # low_confidence low stays
        "D8": "medium",  # missing_source high → medium (cap)
    }

    assert len(result) == 8, f"Expected 8 flags, got {len(result)}"
    for flag in result:
        desc = flag["description"]
        assert flag["severity"] == expected_severities[desc], \
            f"{desc}: expected {expected_severities[desc]}, got {flag['severity']}"


def test_deduplication_snapshot():
    """Same (flag_type, document_id) pair deduplicates; higher severity wins."""
    doc_id = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
    raw_flags = [
        {"flag_type": "unreleased_mortgage", "severity": "medium",
         "title": "UM1", "description": "Desc A", "document_id": doc_id},
        {"flag_type": "unreleased_mortgage", "severity": "critical",
         "title": "UM2", "description": "Desc B", "document_id": doc_id},
    ]
    result = normalize_flags(raw_flags)

    # Both get floor-clamped (unreleased_mortgage floor=high)
    # medium → high, critical stays critical
    # Dedup keeps one with higher severity: critical
    assert len(result) == 1
    assert result[0]["severity"] == "critical"
    assert result[0]["document_id"] == doc_id


def test_normalize_flags_rejects_unknown_types():
    """Only flags in VALID_FLAG_TYPES survive normalization."""
    raw_flags = [
        {"flag_type": "unreleased_mortgage", "severity": "high", "title": "Valid", "description": "Valid flag"},
        {"flag_type": "invented_type", "severity": "high", "title": "Invalid", "description": "Should be dropped"},
        {"flag_type": "another_fake", "severity": "critical", "title": "Invalid", "description": "Should be dropped"},
    ]
    result = normalize_flags(raw_flags)
    assert len(result) == 1
    assert result[0]["flag_type"] == "unreleased_mortgage"


# ---------------------------------------------------------------------------
# Low confidence threshold tests
# ---------------------------------------------------------------------------

def test_low_confidence_at_threshold_no_flag():
    """Document exactly at threshold (0.70) does NOT trigger flag."""
    docs = [MockDoc(id=uuid.uuid4(), doc_type="deed", recording_ref="D-001", confidence=LOW_CONFIDENCE_THRESHOLD)]
    flags = detect_low_confidence(docs)
    assert len(flags) == 0


def test_low_confidence_just_below_threshold():
    """Document at 0.69 triggers flag."""
    docs = [MockDoc(id=uuid.uuid4(), doc_type="deed", recording_ref="D-001", confidence=0.69)]
    flags = detect_low_confidence(docs)
    assert len(flags) == 1
    assert "0.69" in flags[0]["description"]


def test_low_confidence_none_confidence_no_flag():
    """Document with None confidence does NOT trigger flag."""
    docs = [MockDoc(id=uuid.uuid4(), doc_type="deed", recording_ref="D-001", confidence=None)]
    flags = detect_low_confidence(docs)
    assert len(flags) == 0


# ---------------------------------------------------------------------------
# Serialization roundtrip tests
# ---------------------------------------------------------------------------

def test_parse_serialization_roundtrip_golden():
    """Serialize golden documents and verify roundtrip fidelity."""
    docs = _docs_from_golden(GOLDEN_DOCUMENTS)
    # Add required fields for serialization
    for doc in docs:
        doc.needs_review = doc.confidence < LOW_CONFIDENCE_THRESHOLD if doc.confidence else False
        doc.raw_document_id = None

    serialized = _serialize_parse_output(docs)
    deserialized = json.loads(serialized)

    assert len(deserialized) == len(GOLDEN_DOCUMENTS)
    for i, original in enumerate(GOLDEN_DOCUMENTS):
        found = [d for d in deserialized if d["recording_ref"] == original["recording_ref"]]
        assert len(found) == 1, f"Missing doc with ref {original['recording_ref']}"
        assert found[0]["doc_type"] == original["doc_type"]
        assert found[0]["confidence"] == original["confidence"]


def test_chain_serialization_roundtrip_golden():
    """Serialize golden chain output and verify roundtrip fidelity."""
    class MockLink:
        def __init__(self, **kw):
            for k, v in kw.items():
                setattr(self, k, v)

    class MockFlag:
        def __init__(self, **kw):
            for k, v in kw.items():
                setattr(self, k, v)

    links = [
        MockLink(position=1, link_type="conveyance",
                 document_id=GOLDEN_DOCUMENTS[0]["id"],
                 from_party=GOLDEN_DOCUMENTS[0]["grantor"],
                 to_party=GOLDEN_DOCUMENTS[0]["grantee"],
                 effective_date="2015-03-20", is_gap=False, gap_description=None),
        MockLink(position=2, link_type="conveyance",
                 document_id=GOLDEN_DOCUMENTS[2]["id"],
                 from_party=GOLDEN_DOCUMENTS[2]["grantor"],
                 to_party=GOLDEN_DOCUMENTS[2]["grantee"],
                 effective_date="2020-06-15", is_gap=False, gap_description=None),
    ]
    flags_data = detect_all_flags(_docs_from_golden(GOLDEN_DOCUMENTS))
    mock_flags = [MockFlag(**f, ai_explanation=None, chain_link_id=None, status="open") for f in flags_data]

    serialized = _serialize_chain_output(links, mock_flags)
    deserialized = json.loads(serialized)

    assert len(deserialized["chain_links"]) == 2
    assert deserialized["chain_links"][0]["position"] == 1
    assert deserialized["chain_links"][1]["position"] == 2
    assert len(deserialized["flags"]) == len(flags_data)


# ---------------------------------------------------------------------------
# Full pipeline determinism (integration)
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def golden_pipeline_order(db_session: AsyncSession, seed_data):
    """Create an order for full pipeline determinism testing."""
    cs = TACountySource(
        county="Golden", state_code="IL",
        source_type="recorder", availability="digital", is_active=True,
    )
    db_session.add(cs)

    order_id = uuid.uuid4()
    order = TAOrder(
        id=order_id, org_id=TEST_ORG_ID, created_by=TEST_USER_ID,
        property_address="999 Golden St, Golden, IL",
        county="Golden", state_code="IL",
        status="processing", pipeline_stage="order",
    )
    db_session.add(order)
    await db_session.commit()
    return order_id


@pytest.mark.asyncio
async def test_pipeline_output_deterministic(golden_pipeline_order):
    """Run the full pipeline twice — documents, chain links, and flags must be identical."""
    order_id = golden_pipeline_order

    # First run
    await run_pipeline(order_id, TEST_ORG_ID, test_session_factory)

    async with test_session_factory() as db:
        docs1 = (await db.execute(
            select(TADocument).where(TADocument.order_id == order_id).order_by(TADocument.recording_ref)
        )).scalars().all()
        links1 = (await db.execute(
            select(TAChainLink).where(TAChainLink.order_id == order_id).order_by(TAChainLink.position)
        )).scalars().all()
        flags1 = (await db.execute(
            select(TAFlag).where(TAFlag.order_id == order_id).order_by(TAFlag.flag_type, TAFlag.description)
        )).scalars().all()

    doc_types_1 = [(d.doc_type, d.recording_ref, d.confidence) for d in docs1]
    link_types_1 = [(l.position, l.link_type) for l in links1]
    flag_types_1 = [(f.flag_type, f.severity, f.description) for f in flags1]

    assert len(docs1) >= 1

    # Second run — re-run parse/chain/package/complete stages directly
    # (skipping order/retrieve to avoid duplicate source assignments)
    for stage_name in ("parse", "chain", "package", "complete"):
        async with test_session_factory() as db:
            await STAGE_HANDLERS[stage_name](order_id, TEST_ORG_ID, db)
            await db.commit()

    async with test_session_factory() as db:
        docs2 = (await db.execute(
            select(TADocument).where(TADocument.order_id == order_id).order_by(TADocument.recording_ref)
        )).scalars().all()
        links2 = (await db.execute(
            select(TAChainLink).where(TAChainLink.order_id == order_id).order_by(TAChainLink.position)
        )).scalars().all()
        flags2 = (await db.execute(
            select(TAFlag).where(TAFlag.order_id == order_id).order_by(TAFlag.flag_type, TAFlag.description)
        )).scalars().all()

    doc_types_2 = [(d.doc_type, d.recording_ref, d.confidence) for d in docs2]
    link_types_2 = [(l.position, l.link_type) for l in links2]
    flag_types_2 = [(f.flag_type, f.severity, f.description) for f in flags2]

    # Identical business outputs
    assert doc_types_2 == doc_types_1, "Documents differ between runs"
    assert link_types_2 == link_types_1, "Chain links differ between runs"
    assert flag_types_2 == flag_types_1, "Flags differ between runs"


# ---------------------------------------------------------------------------
# Rules version traceability
# ---------------------------------------------------------------------------

def test_rules_version_matches_between_modules():
    """RULES_VERSION in flag_rules.py matches what version_tracker re-exports."""
    from app.micro_apps.title_search.pipeline.version_tracker import RULES_VERSION as vt_version
    from app.micro_apps.title_search.services.flag_rules import RULES_VERSION as fr_version
    assert vt_version == fr_version
    assert vt_version == "ta_flag_rules_v1"
