"""Golden-set / regression tests for deterministic pipeline outputs.

Tests the deterministic layers (flag normalization + readiness scoring)
with fixed inputs and hardcoded expected outputs.  These tests MUST pass
before any version bump of prompts, models, tool schemas, or rule sets.
"""

from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.micro_apps.title_intelligence.models.pack import Pack
from app.micro_apps.title_intelligence.models.extraction import Extraction
from app.micro_apps.title_intelligence.models.flag import Flag
from app.micro_apps.title_intelligence.services.readiness_service import calculate_readiness
from app.micro_apps.title_intelligence.services.flag_rules import normalize_flags
from tests.conftest import TEST_ORG_ID
from tests.title_intelligence.conftest import TEST_PACK_ID

# ---------------------------------------------------------------------------
# Golden inputs
# ---------------------------------------------------------------------------

GOLDEN_EXTRACTIONS = [
    {"type": "requirement", "label": "Requirement 1: Pay off existing mortgage",
     "value": {"description": "Pay off existing mortgage balance"}, "confidence": 0.92},
    {"type": "requirement", "label": "Requirement 2: Obtain release of lien",
     "value": {"description": "Obtain release of mechanics lien"}, "confidence": 0.88},
    {"type": "requirement", "label": "Requirement 3: Record deed of trust",
     "value": {"description": "Record new deed of trust"}, "confidence": 0.95},
    {"type": "endorsement", "label": "ALTA 9 Endorsement",
     "value": {"endorsement_type": "ALTA 9", "status": "present"}, "confidence": 0.90},
    {"type": "endorsement", "label": "ALTA 8.1 Endorsement",
     "value": {"endorsement_type": "ALTA 8.1", "status": "present"}, "confidence": 0.85},
    {"type": "property_info", "label": "Property Address",
     "value": {"address": "123 Main St", "city": "Springfield", "state": "IL"}, "confidence": 0.97},
    {"type": "party", "label": "Buyer: Jane Smith",
     "value": {"name": "Jane Smith", "role": "buyer"}, "confidence": 0.95},
]

GOLDEN_FLAGS_RAW = [
    {
        "flag_type": "unresolved_lien",
        "severity": "high",
        "title": "Outstanding Deed of Trust",
        "description": "Deed of trust not reconveyed",
        "ai_explanation": "Found deed of trust without reconveyance",
        "evidence_refs": [{"page_number": 5, "text_snippet": "Deed of Trust dated 2020-01-15"}],
    },
    {
        "flag_type": "missing_endorsement",
        "severity": "medium",
        "title": "Missing ALTA 5 Endorsement",
        "description": "ALTA 5 endorsement not found",
        "ai_explanation": "No ALTA 5 endorsement detected in document",
        "evidence_refs": [{"page_number": 8, "text_snippet": "Endorsements section"}],
    },
    {
        "flag_type": "requirement_missing_proof",
        "severity": "medium",
        "title": "Requirement 2 Unverified",
        "description": "No proof of mechanics lien release",
        "ai_explanation": "Mechanics lien release not found in documents",
        "evidence_refs": [{"page_number": 3, "text_snippet": "Requirements section"}],
    },
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def golden_pack(db_session: AsyncSession, seed_data):
    """Create the golden pack with fixed extractions and flags."""
    pack = Pack(id=TEST_PACK_ID, org_id=TEST_ORG_ID, name="Golden Test Pack", status="completed")
    db_session.add(pack)

    for ext in GOLDEN_EXTRACTIONS:
        db_session.add(Extraction(
            pack_id=TEST_PACK_ID,
            org_id=TEST_ORG_ID,
            extraction_type=ext["type"],
            label=ext["label"],
            value=ext["value"],
            evidence_refs=[{"page_number": 1, "text_snippet": ext["label"]}],
            confidence=ext["confidence"],
        ))

    for f in GOLDEN_FLAGS_RAW:
        db_session.add(Flag(
            pack_id=TEST_PACK_ID,
            org_id=TEST_ORG_ID,
            flag_type=f["flag_type"],
            severity=f["severity"],
            title=f["title"],
            description=f["description"],
            ai_explanation=f["ai_explanation"],
            evidence_refs=f["evidence_refs"],
        ))

    await db_session.commit()
    return pack


# ---------------------------------------------------------------------------
# Determinism tests — same inputs → identical outputs across N runs
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_readiness_score_deterministic(db_session: AsyncSession, golden_pack):
    """Compute readiness 10x with the same inputs — all results must be identical."""
    results = []
    for _ in range(10):
        r = await calculate_readiness(db_session, TEST_ORG_ID, TEST_PACK_ID)
        results.append(r)

    first = results[0]
    for r in results[1:]:
        assert r.score == first.score
        assert r.status == first.status
        assert r.estimated_days == first.estimated_days
        assert len(r.categories) == len(first.categories)
        for c1, c2 in zip(first.categories, r.categories):
            assert c1.category == c2.category
            assert c1.score == c2.score
            assert c1.satisfied == c2.satisfied
            assert c1.total == c2.total


def test_flag_normalization_deterministic():
    """Normalize the same raw flags 10x — all results must be identical."""
    results = []
    for _ in range(10):
        r = normalize_flags(copy.deepcopy(GOLDEN_FLAGS_RAW))
        results.append(r)

    first = results[0]
    for r in results[1:]:
        assert len(r) == len(first)
        for f1, f2 in zip(first, r):
            assert f1["flag_type"] == f2["flag_type"]
            assert f1["severity"] == f2["severity"]
            assert f1["title"] == f2["title"]


# ---------------------------------------------------------------------------
# Snapshot tests — exact expected values
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_readiness_snapshot(db_session: AsyncSession, golden_pack):
    """Assert exact readiness score, status, categories, and estimated_days."""
    r = await calculate_readiness(db_session, TEST_ORG_ID, TEST_PACK_ID)

    # 3 open flags: 1 high (0.05), 1 medium (0.02), 1 medium (0.02) → penalty_factor = 0.09
    # penalty_multiplier = max(0.4, 1.0 - 0.09) = 0.91
    #
    # Category scores:
    # requirements: 3 extracted, 1 open flag → 2/3 satisfied = 67
    # endorsements: 2 extracted + 1 missing flag → 2/3 present = 67
    # liens: 1 open flag, 0 resolved → 0/1 = 0
    # exceptions: 0 flags → 1.0 = 100
    # consistency: 0 flags → 1.0 = 100
    #
    # weighted = 67*0.35 + 67*0.25 + 0*0.25 + 100*0.10 + 100*0.05
    #          = 23.45 + 16.75 + 0 + 10 + 5 = 55.2
    # After penalty: round(55.2 * 0.91) = round(50.232) = 50

    assert r.score == 50
    assert r.status == "not_ready"
    assert r.estimated_days == 5  # max(unresolved_lien=5, missing_endorsement=2, requirement_missing_proof=5)

    # Category breakdown
    cats = {c.category: c for c in r.categories}
    assert cats["requirements"].score == 67
    assert cats["requirements"].satisfied == 2
    assert cats["requirements"].total == 3
    assert cats["endorsements"].score == 67
    assert cats["endorsements"].satisfied == 2
    assert cats["endorsements"].total == 3
    assert cats["liens"].score == 0
    assert cats["liens"].total == 1
    assert cats["exceptions"].score == 100
    assert cats["consistency"].score == 100


def test_normalize_flags_snapshot():
    """Assert exact output from known raw input."""
    raw = copy.deepcopy(GOLDEN_FLAGS_RAW)
    result = normalize_flags(raw)

    # All 3 flags are valid and on different pages — no dedup
    assert len(result) == 3

    # Sorted by (flag_type, min page): missing_endorsement(8), requirement_missing_proof(3), unresolved_lien(5)
    assert result[0]["flag_type"] == "missing_endorsement"
    assert result[0]["severity"] == "medium"

    assert result[1]["flag_type"] == "requirement_missing_proof"
    assert result[1]["severity"] == "medium"

    assert result[2]["flag_type"] == "unresolved_lien"
    assert result[2]["severity"] == "high"


# ---------------------------------------------------------------------------
# Confidence thresholding tests
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def golden_pack_with_low_confidence(db_session: AsyncSession, seed_data):
    """Pack with a mix of high and low confidence extractions."""
    pack = Pack(id=TEST_PACK_ID, org_id=TEST_ORG_ID, name="Confidence Test Pack", status="completed")
    db_session.add(pack)

    # High-confidence extraction (above threshold)
    db_session.add(Extraction(
        pack_id=TEST_PACK_ID, org_id=TEST_ORG_ID,
        extraction_type="party", label="Buyer: Jane Smith",
        value={"name": "Jane Smith", "role": "buyer"},
        evidence_refs=[{"page_number": 1, "text_snippet": "Buyer: Jane Smith"}],
        confidence=0.95,
    ))
    # Low-confidence extraction (below threshold of 0.5)
    db_session.add(Extraction(
        pack_id=TEST_PACK_ID, org_id=TEST_ORG_ID,
        extraction_type="requirement", label="Possible Requirement",
        value={"description": "Unclear requirement text"},
        evidence_refs=[{"page_number": 3, "text_snippet": "...might require..."}],
        confidence=0.3,
    ))

    await db_session.commit()
    return pack


@pytest.mark.asyncio
async def test_low_confidence_extraction_surfaces_in_checklist(
    db_session: AsyncSession, golden_pack_with_low_confidence
):
    """Low-confidence extractions appear as needs_review in the checklist."""
    r = await calculate_readiness(db_session, TEST_ORG_ID, TEST_PACK_ID)

    needs_review = [item for item in r.checklist if item.status == "needs_review"]
    assert len(needs_review) == 1
    assert "Low confidence" in needs_review[0].label
    assert "30%" in needs_review[0].label


@pytest.mark.asyncio
async def test_high_confidence_extraction_not_flagged(
    db_session: AsyncSession, golden_pack_with_low_confidence
):
    """High-confidence extractions should not appear as needs_review."""
    r = await calculate_readiness(db_session, TEST_ORG_ID, TEST_PACK_ID)

    needs_review_labels = [item.label for item in r.checklist if item.status == "needs_review"]
    assert not any("Jane Smith" in label for label in needs_review_labels)
