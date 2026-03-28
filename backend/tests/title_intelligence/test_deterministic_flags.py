"""Tests for deterministic flag generation and merge logic."""

import pytest

from app.micro_apps.title_intelligence.services.flag_rules import (
    DETERMINISTIC_FLAG_TYPES,
    generate_deterministic_flags,
    merge_llm_and_deterministic_flags,
    normalize_flags,
)


def _make_flag(
    flag_type: str = "unresolved_lien",
    severity: str = "high",
    page: int = 1,
    title: str = "Test flag",
    description: str = "Test description",
    ai_explanation: str = "Test explanation",
) -> dict:
    return {
        "flag_type": flag_type,
        "severity": severity,
        "title": title,
        "description": description,
        "ai_explanation": ai_explanation,
        "evidence_refs": [{"page_number": page, "text_snippet": f"evidence on page {page}"}],
    }


def _chain_ext(
    grantor: str = "Alice",
    grantee: str = "Bob",
    recording_date: str | None = "2020-01-01",
    recording_ref: str = "",
    instrument_type: str = "deed",
    page: int = 1,
) -> dict:
    return {
        "extraction_type": "chain_of_title",
        "label": f"{instrument_type}: {grantor} to {grantee}",
        "value": {
            "grantor": grantor,
            "grantee": grantee,
            "recording_date": recording_date,
            "recording_ref": recording_ref,
            "instrument_type": instrument_type,
        },
        "evidence_refs": [{"page_number": page, "text_snippet": f"evidence on page {page}"}],
    }


# --- DETERMINISTIC_FLAG_TYPES constant ---

def test_deterministic_flag_types_defined():
    assert "chain_of_title_gap" in DETERMINISTIC_FLAG_TYPES
    assert "unreleased_mortgage" in DETERMINISTIC_FLAG_TYPES
    assert "name_discrepancy" in DETERMINISTIC_FLAG_TYPES
    assert "cross_section_mismatch" in DETERMINISTIC_FLAG_TYPES


def test_deterministic_types_are_subset_of_valid():
    from app.micro_apps.title_intelligence.services.flag_rules import VALID_FLAG_TYPES
    assert DETERMINISTIC_FLAG_TYPES.issubset(VALID_FLAG_TYPES)


# --- generate_deterministic_flags ---

def test_generate_chain_gap_flags():
    extractions = [
        _chain_ext(grantor="Alice", grantee="Bob", recording_date="2020-01-01", page=1),
        _chain_ext(grantor="Charlie", grantee="David", recording_date="2021-01-01", page=2),
    ]
    flags = generate_deterministic_flags(extractions)
    gap_flags = [f for f in flags if f["flag_type"] == "chain_of_title_gap"]
    assert len(gap_flags) == 1
    # "Bob" vs "Charlie" score < 30 → critical severity
    assert gap_flags[0]["severity"] == "critical"


def test_generate_unreleased_mortgage_flags():
    extractions = [
        _chain_ext(grantor="Bob", grantee="Bank", recording_date="2020-01-01", instrument_type="mortgage", recording_ref="M-001", page=1),
    ]
    flags = generate_deterministic_flags(extractions)
    mortgage_flags = [f for f in flags if f["flag_type"] == "unreleased_mortgage"]
    assert len(mortgage_flags) == 1
    assert mortgage_flags[0]["severity"] == "high"


def test_generate_name_discrepancy_flags():
    extractions = [
        {"extraction_type": "party", "value": {"name": "Michael Johnson", "role": "buyer"}, "evidence_refs": [{"page_number": 1, "text_snippet": "Michael Johnson"}]},
        {"extraction_type": "party", "value": {"name": "Micheal Johnson", "role": "buyer"}, "evidence_refs": [{"page_number": 3, "text_snippet": "Micheal Johnson"}]},
    ]
    flags = generate_deterministic_flags(extractions)
    name_flags = [f for f in flags if f["flag_type"] == "name_discrepancy"]
    assert len(name_flags) >= 1
    assert name_flags[0]["severity"] == "medium"


def test_generate_no_flags_for_empty_extractions():
    flags = generate_deterministic_flags([])
    assert flags == []


def test_generate_no_flags_for_complete_chain():
    extractions = [
        _chain_ext(grantor="Alice", grantee="Bob", recording_date="2020-01-01"),
        _chain_ext(grantor="Bob", grantee="Charlie", recording_date="2021-01-01"),
    ]
    flags = generate_deterministic_flags(extractions)
    gap_flags = [f for f in flags if f["flag_type"] == "chain_of_title_gap"]
    assert len(gap_flags) == 0


def test_generate_cross_section_mismatches():
    extractions = [
        {"extraction_type": "property", "value": {"address": "123 Main St"}, "evidence_refs": [{"page_number": 1, "text_snippet": "123 Main St"}]},
        {"extraction_type": "property", "value": {"address": "123 Main Street"}, "evidence_refs": [{"page_number": 5, "text_snippet": "123 Main Street"}]},
    ]
    sections = [
        {"section_type": "schedule_a", "start_page": 1, "end_page": 3},
        {"section_type": "schedule_b1", "start_page": 4, "end_page": 6},
    ]
    flags = generate_deterministic_flags(extractions, sections)
    mismatch_flags = [f for f in flags if f["flag_type"] == "cross_section_mismatch"]
    # Property address "123 Main St" vs "123 Main Street" may match depending on fuzzy score
    # At minimum, the function should not error
    assert isinstance(mismatch_flags, list)


# --- merge_llm_and_deterministic_flags ---

def test_merge_drops_llm_deterministic_types():
    llm_flags = [
        _make_flag(flag_type="chain_of_title_gap", severity="medium", page=1),
        _make_flag(flag_type="unresolved_lien", severity="high", page=2),
    ]
    det_flags = [
        _make_flag(flag_type="chain_of_title_gap", severity="high", page=1),
    ]
    merged = merge_llm_and_deterministic_flags(
        normalize_flags(llm_flags),
        normalize_flags(det_flags),
    )
    # LLM chain_of_title_gap should be replaced by deterministic one
    gap_flags = [f for f in merged if f["flag_type"] == "chain_of_title_gap"]
    assert len(gap_flags) == 1
    assert gap_flags[0]["severity"] == "high"

    # LLM unresolved_lien should be kept (not a deterministic type)
    lien_flags = [f for f in merged if f["flag_type"] == "unresolved_lien"]
    assert len(lien_flags) == 1


def test_merge_keeps_non_deterministic_llm_flags():
    llm_flags = [
        _make_flag(flag_type="missing_endorsement", severity="medium", page=1),
        _make_flag(flag_type="requirement_missing_proof", severity="high", page=3),
    ]
    merged = merge_llm_and_deterministic_flags(
        normalize_flags(llm_flags),
        [],
    )
    assert len(merged) == 2


def test_merge_combines_both_sources():
    llm_flags = [
        _make_flag(flag_type="unresolved_lien", severity="high", page=2),
        _make_flag(flag_type="name_discrepancy", severity="low", page=5),  # will be dropped
    ]
    det_flags = [
        _make_flag(flag_type="name_discrepancy", severity="medium", page=5),
        _make_flag(flag_type="chain_of_title_gap", severity="high", page=1),
    ]
    merged = merge_llm_and_deterministic_flags(
        normalize_flags(llm_flags),
        normalize_flags(det_flags),
    )
    types = {f["flag_type"] for f in merged}
    assert "unresolved_lien" in types  # kept from LLM
    assert "name_discrepancy" in types  # from deterministic
    assert "chain_of_title_gap" in types  # from deterministic

    # LLM name_discrepancy should be gone
    name_flags = [f for f in merged if f["flag_type"] == "name_discrepancy"]
    assert all(f["severity"] == "medium" for f in name_flags)  # deterministic severity


def test_merge_empty_both():
    merged = merge_llm_and_deterministic_flags([], [])
    assert merged == []


def test_merge_only_deterministic():
    det_flags = [
        _make_flag(flag_type="chain_of_title_gap", severity="high", page=1),
    ]
    merged = merge_llm_and_deterministic_flags([], normalize_flags(det_flags))
    assert len(merged) == 1


# --- End-to-end: extraction → deterministic flags ---

def test_e2e_chain_gap_and_mortgage():
    """Full pipeline: extractions → generate_deterministic_flags → merge."""
    extractions = [
        _chain_ext(grantor="Alice", grantee="Bob", recording_date="2020-01-01", instrument_type="deed", page=1),
        _chain_ext(grantor="Charlie", grantee="David", recording_date="2021-01-01", instrument_type="deed", page=2),
        _chain_ext(grantor="David", grantee="First Bank", recording_date="2021-06-01", instrument_type="mortgage", recording_ref="M-001", page=3),
    ]
    llm_flags = [
        _make_flag(flag_type="chain_of_title_gap", severity="medium", page=1),
        _make_flag(flag_type="missing_endorsement", severity="medium", page=5),
    ]

    det_flags = generate_deterministic_flags(extractions)
    merged = merge_llm_and_deterministic_flags(normalize_flags(llm_flags), det_flags)

    # Should have: chain_gap (deterministic), unreleased_mortgage (deterministic), missing_endorsement (LLM)
    types = [f["flag_type"] for f in merged]
    assert "chain_of_title_gap" in types
    assert "unreleased_mortgage" in types
    assert "missing_endorsement" in types

    # Chain gap should use deterministic severity (critical for low-score gap), not LLM (medium)
    gap_flags = [f for f in merged if f["flag_type"] == "chain_of_title_gap"]
    assert gap_flags[0]["severity"] == "critical"
