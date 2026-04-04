"""Golden-set / regression tests for deterministic pipeline outputs.

Tests the deterministic layers (flag normalization, chain building,
party normalization, version tracking) with fixed inputs and hardcoded
expected outputs.  These tests MUST pass before any version bump of
prompts, models, tool schemas, or rule sets.
"""

from __future__ import annotations

import copy
import hashlib
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.micro_apps.title_intelligence.models.pack import Pack
from app.micro_apps.title_intelligence.models.extraction import Extraction
from app.micro_apps.title_intelligence.models.flag import Flag
from app.micro_apps.title_intelligence.services.flag_rules import (
    normalize_flags,
    generate_deterministic_flags,
    merge_llm_and_deterministic_flags,
    RULES_VERSION,
)
from app.micro_apps.title_intelligence.services.chain_builder import (
    build_chain,
    CHAIN_BUILDER_VERSION,
)
from app.micro_apps.title_intelligence.services.party_normalizer import (
    normalize_party_name,
    match_parties,
    find_name_discrepancies,
    NORMALIZER_VERSION,
)
from app.micro_apps.title_intelligence.pipeline.version_tracker import (
    hash_string,
    compute_ingestion_output_hash,
    compute_examiner_cache_key,
    compute_summary_cache_key,
)
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


# ===========================================================================
# Phase 1b: Chain builder golden-set tests
# ===========================================================================

# Golden chain extractions — 5 entries: 2 deeds, 1 mortgage, 1 release, 1 with date gap
GOLDEN_CHAIN_EXTRACTIONS = [
    {
        "extraction_type": "chain_of_title",
        "value": {
            "grantor": "Alice Adams",
            "grantee": "Bob Brown",
            "recording_date": "2015-03-20",
            "instrument_type": "deed",
            "recording_ref": "2015-001234",
        },
        "evidence_refs": [{"page_number": 1, "text_snippet": "Warranty Deed 2015"}],
    },
    {
        "extraction_type": "chain_of_title",
        "value": {
            "grantor": "Bob Brown",
            "grantee": "Charlie Clark",
            "recording_date": "2018-06-15",
            "instrument_type": "deed",
            "recording_ref": "2018-005678",
        },
        "evidence_refs": [{"page_number": 3, "text_snippet": "Warranty Deed 2018"}],
    },
    {
        "extraction_type": "chain_of_title",
        "value": {
            "grantor": "Charlie Clark",
            "grantee": "First National Bank",
            "recording_date": "2018-06-15",
            "instrument_type": "mortgage",
            "recording_ref": "MTG-2018-001",
        },
        "evidence_refs": [{"page_number": 5, "text_snippet": "Mortgage 2018"}],
    },
    {
        "extraction_type": "chain_of_title",
        "value": {
            "grantor": "First National Bank",
            "grantee": "Charlie Clark",
            "recording_date": "2022-01-10",
            "instrument_type": "release",
            "recording_ref": "MTG-2018-001",  # matches mortgage
        },
        "evidence_refs": [{"page_number": 7, "text_snippet": "Satisfaction of Mortgage"}],
    },
    {
        "extraction_type": "chain_of_title",
        "value": {
            "grantor": "Eve Evans",  # GAP: Charlie Clark → Eve Evans (not matching)
            "grantee": "Frank Foster",
            "recording_date": "2023-09-01",
            "instrument_type": "deed",
            "recording_ref": "2023-009012",
        },
        "evidence_refs": [{"page_number": 9, "text_snippet": "Warranty Deed 2023"}],
    },
]

# Same chain but without the gap (Charlie Clark properly continues)
GOLDEN_CHAIN_COMPLETE = [
    GOLDEN_CHAIN_EXTRACTIONS[0],  # Alice → Bob deed
    GOLDEN_CHAIN_EXTRACTIONS[1],  # Bob → Charlie deed
    GOLDEN_CHAIN_EXTRACTIONS[2],  # Charlie → Bank mortgage
    GOLDEN_CHAIN_EXTRACTIONS[3],  # Bank → Charlie release
    {
        "extraction_type": "chain_of_title",
        "value": {
            "grantor": "Charlie Clark",
            "grantee": "Frank Foster",
            "recording_date": "2023-09-01",
            "instrument_type": "deed",
            "recording_ref": "2023-009012",
        },
        "evidence_refs": [{"page_number": 9, "text_snippet": "Warranty Deed 2023"}],
    },
]

# Chain with unreleased mortgage (no matching release)
GOLDEN_CHAIN_UNRELEASED = [
    GOLDEN_CHAIN_EXTRACTIONS[0],  # Alice → Bob deed
    GOLDEN_CHAIN_EXTRACTIONS[1],  # Bob → Charlie deed
    GOLDEN_CHAIN_EXTRACTIONS[2],  # Charlie → Bank mortgage (no release!)
]


def test_chain_builder_deterministic_10_runs():
    """build_chain 10x with identical input → identical output every time."""
    results = []
    for _ in range(10):
        result = build_chain(copy.deepcopy(GOLDEN_CHAIN_EXTRACTIONS))
        results.append(result)

    first = results[0]
    for r in results[1:]:
        assert r.total_links == first.total_links
        assert r.chain_complete == first.chain_complete
        assert len(r.links) == len(first.links)
        assert len(r.gaps) == len(first.gaps)
        assert len(r.unreleased_mortgages) == len(first.unreleased_mortgages)
        for l1, l2 in zip(first.links, r.links):
            assert l1.position == l2.position
            assert l1.grantor == l2.grantor
            assert l1.grantee == l2.grantee
            assert l1.instrument_type == l2.instrument_type


def test_chain_builder_snapshot_with_gap():
    """Chain with gap: Alice→Bob→Charlie→(gap)→Eve→Frank."""
    result = build_chain(GOLDEN_CHAIN_EXTRACTIONS)
    assert result.chain_complete is False
    assert len(result.gaps) == 1

    gap = result.gaps[0]
    assert gap.expected_grantor == "Charlie Clark"
    assert gap.actual_grantor == "Eve Evans"
    assert gap.match_score < 85.0  # well below threshold

    # 5 links total (2 deeds + 1 mortgage + 1 release + 1 deed with gap)
    assert result.total_links == 5

    # Mortgage is released (matching recording_ref)
    assert len(result.unreleased_mortgages) == 0


def test_chain_builder_snapshot_unreleased_mortgage():
    """Chain with mortgage and no matching release."""
    result = build_chain(GOLDEN_CHAIN_UNRELEASED)

    assert len(result.unreleased_mortgages) == 1
    um = result.unreleased_mortgages[0]
    assert um.recording_ref == "MTG-2018-001"
    assert um.mortgage_link.grantee == "First National Bank"

    # No gap: Alice → Bob → Charlie is a clean conveyance chain
    assert result.chain_complete is True
    assert len(result.gaps) == 0


def test_chain_builder_snapshot_complete_chain():
    """Complete chain: no gaps, all mortgages released."""
    result = build_chain(GOLDEN_CHAIN_COMPLETE)
    assert result.chain_complete is True
    assert len(result.gaps) == 0
    assert len(result.unreleased_mortgages) == 0
    assert result.total_links == 5


def test_chain_builder_empty_input():
    """Empty extraction list returns empty ChainResult."""
    result = build_chain([])
    assert result.total_links == 0
    assert result.chain_complete is True
    assert result.links == []
    assert result.gaps == []


def test_chain_builder_chronological_sort():
    """Links are sorted by recording_date."""
    result = build_chain(GOLDEN_CHAIN_EXTRACTIONS)
    dates = [l.recording_date for l in result.links if l.recording_date]
    assert dates == sorted(dates)


# ===========================================================================
# Phase 1c: Party normalizer golden-set tests
# ===========================================================================

# 10 known inputs → expected normalized outputs
PARTY_NORMALIZER_GOLDEN = [
    ("John Smith", "john smith", False, ("john", "smith")),
    ("ALICE JOHNSON", "alice johnson", False, ("alice", "johnson")),
    ("Robert J. Smith Jr.", "j robert smith", False, ("j", "robert", "smith")),
    ("Sarah Williams-Jones", "sarah williams-jones", False, ("sarah", "williams-jones")),
    ("First National Bank, N.A.", "bank first national", True, ("bank", "first", "national")),
    ("ABC Holdings LLC", "abc holdings", True, ("abc", "holdings")),
    ("The Johnson Family Trust", "family johnson", True, ("family", "johnson")),
    ("Pacific Savings and Loan", "loan pacific savings", True, ("loan", "pacific", "savings")),
    ("", "", False, ()),
    ("  ", "", False, ()),
]


def test_normalize_party_name_snapshot():
    """10 known inputs → exact expected normalized outputs."""
    for original, expected_norm, expected_entity, expected_tokens in PARTY_NORMALIZER_GOLDEN:
        result = normalize_party_name(original)
        assert result.normalized == expected_norm, \
            f"normalize({original!r}): expected {expected_norm!r}, got {result.normalized!r}"
        assert result.is_entity == expected_entity, \
            f"is_entity({original!r}): expected {expected_entity}, got {result.is_entity}"
        assert result.canonical_tokens == expected_tokens, \
            f"tokens({original!r}): expected {expected_tokens}, got {result.canonical_tokens}"


def test_match_parties_deterministic_10_runs():
    """Same pair → same match result 10x."""
    results = []
    for _ in range(10):
        r = match_parties("Robert J Smith", "Robert Smith", threshold=85.0)
        results.append((r.score, r.is_match, r.match_method))

    first = results[0]
    for r in results[1:]:
        assert r == first


def test_match_parties_exact():
    """Identical names after normalization → exact match with score 100."""
    result = match_parties("John Smith", "john smith", threshold=85.0)
    assert result.is_match is True
    assert result.score == 100.0
    assert result.match_method == "exact"


def test_match_parties_fuzzy():
    """Similar but not identical names → fuzzy match above threshold."""
    result = match_parties("Robert J Smith", "Robert Smith", threshold=85.0)
    assert result.is_match is True
    assert 85.0 <= result.score < 100.0
    assert result.match_method == "fuzzy"


def test_match_parties_no_match():
    """Completely different names → no match."""
    result = match_parties("Alice Johnson", "Xerxes Zimmerman", threshold=85.0)
    assert result.is_match is False
    assert result.match_method == "no_match"


def test_find_name_discrepancies_snapshot():
    """Known extractions → exact discrepancy list."""
    extractions = [
        {"extraction_type": "party", "value": {"name": "Robert J Smith", "role": "buyer"},
         "evidence_refs": [{"page_number": 1}]},
        {"extraction_type": "party", "value": {"name": "Robert Smith", "role": "buyer"},
         "evidence_refs": [{"page_number": 3}]},
        {"extraction_type": "party", "value": {"name": "Alice Johnson", "role": "seller"},
         "evidence_refs": [{"page_number": 2}]},
    ]
    discrepancies = find_name_discrepancies(extractions, threshold=85.0)

    # Only Robert J Smith vs Robert Smith should be a near-match
    assert len(discrepancies) == 1
    d = discrepancies[0]
    assert "Robert" in d["name_a"] or "Robert" in d["name_b"]
    assert d["match_method"] == "fuzzy"
    assert 85.0 <= d["score"] < 100.0


def test_find_name_discrepancies_deterministic_10_runs():
    """find_name_discrepancies 10x → identical output."""
    extractions = [
        {"extraction_type": "party", "value": {"name": "Robert J Smith", "role": "buyer"},
         "evidence_refs": [{"page_number": 1}]},
        {"extraction_type": "party", "value": {"name": "Robert Smith", "role": "buyer"},
         "evidence_refs": [{"page_number": 3}]},
    ]
    results = [find_name_discrepancies(copy.deepcopy(extractions)) for _ in range(10)]
    first = results[0]
    for r in results[1:]:
        assert len(r) == len(first)
        for d1, d2 in zip(first, r):
            assert d1["name_a"] == d2["name_a"]
            assert d1["name_b"] == d2["name_b"]
            assert d1["score"] == d2["score"]


# ===========================================================================
# Phase 1d: Version tracker hash stability tests
# ===========================================================================


def _make_version_info(**overrides):
    """Build a baseline version_info dict for testing."""
    base = {
        "ai_model": "gemini/gemini-2.5-flash",
        "ingestion_prompt_hash": hash_string("test prompt"),
        "extraction_tool_hash": hash_string("test tool"),
        "rules_version": "weighted_5cat_v2",
        "triage_prompt_hash": hash_string("triage prompt"),
        "extraction_registry_hash": hash_string("registry"),
        "flag_rules_version": RULES_VERSION,
        "chain_builder_version": CHAIN_BUILDER_VERSION,
        "normalizer_version": NORMALIZER_VERSION,
    }
    base.update(overrides)
    return base


def test_compute_examiner_cache_key_deterministic():
    """Same inputs → same hash 10x."""
    vi = _make_version_info()
    hashes = [compute_examiner_cache_key("file_abc123", vi) for _ in range(10)]
    assert len(set(hashes)) == 1  # all identical


def test_compute_examiner_cache_key_changes_on_model_change():
    """Different model → different hash."""
    vi_a = _make_version_info(ai_model="gemini/gemini-2.5-flash")
    vi_b = _make_version_info(ai_model="anthropic/claude-sonnet-4-20250514")
    hash_a = compute_examiner_cache_key("file_abc123", vi_a)
    hash_b = compute_examiner_cache_key("file_abc123", vi_b)
    assert hash_a != hash_b


def test_compute_examiner_cache_key_changes_on_prompt_change():
    """Different prompt → different hash."""
    vi_a = _make_version_info(ingestion_prompt_hash=hash_string("prompt v1"))
    vi_b = _make_version_info(ingestion_prompt_hash=hash_string("prompt v2"))
    hash_a = compute_examiner_cache_key("file_abc123", vi_a)
    hash_b = compute_examiner_cache_key("file_abc123", vi_b)
    assert hash_a != hash_b


def test_compute_examiner_cache_key_changes_on_file_change():
    """Different file hash → different cache key."""
    vi = _make_version_info()
    hash_a = compute_examiner_cache_key("file_abc123", vi)
    hash_b = compute_examiner_cache_key("file_xyz789", vi)
    assert hash_a != hash_b


def test_compute_examiner_cache_key_changes_on_rules_version():
    """Different rules_version → different cache key."""
    vi_a = _make_version_info(flag_rules_version="flag_rules_v3")
    vi_b = _make_version_info(flag_rules_version="flag_rules_v4")
    hash_a = compute_examiner_cache_key("file_abc123", vi_a)
    hash_b = compute_examiner_cache_key("file_abc123", vi_b)
    assert hash_a != hash_b


def test_compute_ingestion_output_hash_deterministic():
    """Same sections + extractions → same hash 10x."""
    sections = [{"section_type": "schedule_a", "start_page": 1, "end_page": 5}]
    extractions = [{"extraction_type": "party", "label": "Buyer", "value": {"name": "Alice"}}]
    hashes = [compute_ingestion_output_hash(sections, extractions) for _ in range(10)]
    assert len(set(hashes)) == 1


def test_compute_ingestion_output_hash_order_independent():
    """Hash is the same regardless of input order."""
    sections_a = [
        {"section_type": "schedule_a", "start_page": 1, "end_page": 5},
        {"section_type": "schedule_b1", "start_page": 6, "end_page": 10},
    ]
    sections_b = list(reversed(sections_a))
    extractions = [{"extraction_type": "party", "label": "Buyer", "value": {"name": "Alice"}}]
    hash_a = compute_ingestion_output_hash(sections_a, extractions)
    hash_b = compute_ingestion_output_hash(sections_b, extractions)
    assert hash_a == hash_b


def test_hash_string_deterministic():
    """hash_string produces consistent SHA-256 hex digest."""
    h = hash_string("hello world")
    assert h == hashlib.sha256(b"hello world").hexdigest()
    assert hash_string("hello world") == h  # stable


# ===========================================================================
# Phase 1d: Rules version traceability across modules
# ===========================================================================


def test_rules_version_matches_between_modules():
    """RULES_VERSION used in flag_rules.py matches version_tracker reference."""
    from app.micro_apps.title_intelligence.services.flag_rules import RULES_VERSION as fr_ver
    from app.micro_apps.title_intelligence.services.chain_builder import CHAIN_BUILDER_VERSION as cb_ver
    from app.micro_apps.title_intelligence.services.party_normalizer import NORMALIZER_VERSION as np_ver

    # All version strings are non-empty and stable
    assert fr_ver == "flag_rules_v4"
    assert cb_ver == "chain_builder_v1"
    assert np_ver == "party_norm_v1"


# ===========================================================================
# Phase 1e: Full pipeline round-trip determinism (mocked AI)
# ===========================================================================


def test_full_deterministic_pipeline_roundtrip():
    """Mock AI, run deterministic pipeline 2x, assert identical flags.

    This test exercises the full deterministic path: extractions → chain build
    → generate_deterministic_flags → merge with LLM flags → normalize.
    """
    # Chain with gap (Eve not matching Charlie) AND unreleased mortgage (no release)
    mock_chain = [
        GOLDEN_CHAIN_EXTRACTIONS[0],  # Alice → Bob deed
        GOLDEN_CHAIN_EXTRACTIONS[1],  # Bob → Charlie deed
        GOLDEN_CHAIN_EXTRACTIONS[2],  # Charlie → Bank mortgage (no release!)
        GOLDEN_CHAIN_EXTRACTIONS[4],  # Eve → Frank deed (gap: Charlie ≠ Eve)
    ]
    mock_extractions = copy.deepcopy(mock_chain) + [
        {
            "extraction_type": "party",
            "value": {"name": "Robert J Smith", "role": "buyer"},
            "evidence_refs": [{"page_number": 2}],
        },
        {
            "extraction_type": "party",
            "value": {"name": "Robert Smith", "role": "buyer"},
            "evidence_refs": [{"page_number": 4}],
        },
    ]

    # Simulated LLM flag output (what AI returns before rules engine)
    mock_llm_flags = [
        {
            "flag_type": "chain_of_title_gap",  # will be replaced by deterministic
            "severity": "medium",
            "title": "LLM detected gap",
            "description": "Gap in ownership",
            "evidence_refs": [{"page_number": 9}],
        },
        {
            "flag_type": "missing_endorsement",  # will be kept (non-deterministic)
            "severity": "medium",
            "title": "Missing ALTA 5",
            "description": "No ALTA 5 endorsement",
            "evidence_refs": [{"page_number": 12}],
        },
    ]

    results = []
    for _ in range(2):
        # Run deterministic pipeline: generate flags + merge + normalize
        det_flags = generate_deterministic_flags(copy.deepcopy(mock_extractions))
        llm_normalized = normalize_flags(copy.deepcopy(mock_llm_flags))
        merged = merge_llm_and_deterministic_flags(llm_normalized, det_flags)
        results.append(merged)

    # Both runs must produce identical output
    assert len(results[0]) == len(results[1])
    for f1, f2 in zip(results[0], results[1]):
        assert f1["flag_type"] == f2["flag_type"]
        assert f1["severity"] == f2["severity"]
        assert f1["title"] == f2["title"]
        assert f1["description"] == f2["description"]

    # Verify expected content
    flag_types = {f["flag_type"] for f in results[0]}
    # Deterministic: chain_of_title_gap (Charlie→Eve), unreleased_mortgage, name_discrepancy
    # LLM (kept): missing_endorsement
    assert "chain_of_title_gap" in flag_types
    assert "unreleased_mortgage" in flag_types
    assert "name_discrepancy" in flag_types
    assert "missing_endorsement" in flag_types


# ---------------------------------------------------------------------------
# Confidence thresholding tests
# ---------------------------------------------------------------------------

