"""Tests for the deterministic flag rule engine.

Covers:
- RULES_VERSION / VALID_FLAG_TYPES / DETERMINISTIC_FLAG_TYPES constants
- Severity floor and cap application
- Deterministic flag generators (chain gaps, unreleased mortgages,
  name discrepancies, cross-section mismatches)
- generate_deterministic_flags orchestration
- merge_llm_and_deterministic_flags replacement logic
- normalize_flags validation, dedup, and deterministic sort
"""

import copy

import pytest

from app.micro_apps.title_intelligence.services.flag_rules import (
    DETERMINISTIC_FLAG_TYPES,
    RULES_VERSION,
    SEVERITY_CAP,
    SEVERITY_FLOOR,
    VALID_FLAG_TYPES,
    VALID_SEVERITIES,
    normalize_flags,
    detect_chain_gaps,
    detect_unreleased_mortgages_from_chain,
    detect_name_discrepancies,
    detect_cross_section_mismatches,
    generate_deterministic_flags,
    merge_llm_and_deterministic_flags,
)
from app.micro_apps.title_intelligence.services.chain_builder import (
    ChainLink,
    ChainGap,
    ChainResult,
    UnreleasedMortgage,
)


def _make_flag(
    flag_type: str = "unresolved_lien",
    severity: str = "high",
    page: int = 1,
    title: str = "Test flag",
    description: str = "Test description",
    ai_explanation: str = "Test explanation",
    extra_refs: list | None = None,
) -> dict:
    refs = [{"page_number": page, "text_snippet": f"evidence on page {page}"}]
    if extra_refs:
        refs.extend(extra_refs)
    return {
        "flag_type": flag_type,
        "severity": severity,
        "title": title,
        "description": description,
        "ai_explanation": ai_explanation,
        "evidence_refs": refs,
    }


# --- Severity floor ---

def test_severity_floor_unresolved_lien():
    """unresolved_lien severity must be at least high."""
    flag = _make_flag(flag_type="unresolved_lien", severity="low")
    result = normalize_flags([flag])
    assert len(result) == 1
    assert result[0]["severity"] == "high"


def test_severity_floor_missing_endorsement():
    """missing_endorsement severity must be at least medium."""
    flag = _make_flag(flag_type="missing_endorsement", severity="low")
    result = normalize_flags([flag])
    assert len(result) == 1
    assert result[0]["severity"] == "medium"


def test_severity_floor_does_not_lower():
    """Floor should not lower a severity that is already above the floor."""
    flag = _make_flag(flag_type="unresolved_lien", severity="critical")
    result = normalize_flags([flag])
    assert result[0]["severity"] == "critical"


# --- Severity cap ---

def test_severity_cap_cross_section_mismatch():
    """cross_section_mismatch is capped at medium."""
    flag = _make_flag(flag_type="cross_section_mismatch", severity="critical")
    result = normalize_flags([flag])
    assert result[0]["severity"] == "medium"


def test_severity_cap_does_not_raise():
    """Cap should not raise a severity that is already below the cap."""
    flag = _make_flag(flag_type="cross_section_mismatch", severity="low")
    result = normalize_flags([flag])
    assert result[0]["severity"] == "low"


# --- Invalid flag_type rejection ---

def test_invalid_flag_type_dropped():
    """Flags with unrecognized flag_type are dropped."""
    flag = _make_flag(flag_type="invented_type")
    result = normalize_flags([flag])
    assert len(result) == 0


def test_all_valid_types_accepted():
    """All members of VALID_FLAG_TYPES pass validation."""
    flags = [_make_flag(flag_type=ft) for ft in VALID_FLAG_TYPES]
    result = normalize_flags(flags)
    assert len(result) == len(VALID_FLAG_TYPES)


# --- Evidence requirement ---

def test_empty_evidence_dropped():
    """Flags with empty evidence_refs are dropped."""
    flag = _make_flag()
    flag["evidence_refs"] = []
    result = normalize_flags([flag])
    assert len(result) == 0


def test_no_evidence_key_dropped():
    """Flags with None evidence_refs are dropped."""
    flag = _make_flag()
    flag["evidence_refs"] = None
    result = normalize_flags([flag])
    assert len(result) == 0


# --- Deduplication ---

def test_dedup_overlapping_pages():
    """Same flag_type + overlapping pages should merge into one."""
    f1 = _make_flag(flag_type="unresolved_lien", severity="high", page=5)
    f2 = _make_flag(flag_type="unresolved_lien", severity="medium", page=5,
                    title="Duplicate lien flag")
    result = normalize_flags([f1, f2])
    assert len(result) == 1
    # Keep highest severity
    assert result[0]["severity"] == "high"


def test_dedup_different_pages_no_merge():
    """Same flag_type but non-overlapping pages stay separate."""
    f1 = _make_flag(flag_type="unresolved_lien", severity="high", page=1)
    f2 = _make_flag(flag_type="unresolved_lien", severity="high", page=10)
    result = normalize_flags([f1, f2])
    assert len(result) == 2


def test_dedup_different_types_no_merge():
    """Different flag_types on the same page stay separate."""
    f1 = _make_flag(flag_type="unresolved_lien", severity="high", page=5)
    f2 = _make_flag(flag_type="missing_endorsement", severity="medium", page=5)
    result = normalize_flags([f1, f2])
    assert len(result) == 2


# --- Deterministic sort ---

def test_sort_order():
    """Output is sorted by (flag_type, min page_number)."""
    flags = [
        _make_flag(flag_type="unresolved_lien", page=10),
        _make_flag(flag_type="missing_endorsement", page=1),
        _make_flag(flag_type="unresolved_lien", page=2),
    ]
    result = normalize_flags(flags)
    types_and_pages = [(f["flag_type"], min(
        r["page_number"] for r in f["evidence_refs"]
    )) for f in result]
    assert types_and_pages == [
        ("missing_endorsement", 1),
        ("unresolved_lien", 2),
        ("unresolved_lien", 10),
    ]


# --- Unknown severity defaults to medium ---

def test_unknown_severity_defaults_to_medium():
    """Unrecognized severity values default to medium."""
    flag = _make_flag(flag_type="requirement_missing_proof", severity="extreme")
    result = normalize_flags([flag])
    assert result[0]["severity"] == "medium"


# --- Rules version constant ---

def test_rules_version_set():
    """RULES_VERSION constant is defined and non-empty."""
    assert RULES_VERSION == "flag_rules_v4"


# --- Deterministic flag types ---

def test_deterministic_flag_types_defined():
    """DETERMINISTIC_FLAG_TYPES is defined and all types are valid."""
    assert len(DETERMINISTIC_FLAG_TYPES) == 4
    assert DETERMINISTIC_FLAG_TYPES.issubset(VALID_FLAG_TYPES)


# --- Input not mutated ---

def test_input_not_mutated():
    """normalize_flags should not mutate the input list."""
    original = [_make_flag(flag_type="unresolved_lien", severity="low")]
    import copy
    snapshot = copy.deepcopy(original)
    normalize_flags(original)
    assert original == snapshot


# --- New flag types (v4) ---

def test_new_flag_types_valid():
    """All 5 new flag types are in VALID_FLAG_TYPES."""
    new_types = {"mineral_rights", "trust_issue", "estate_issue", "vesting_issue", "tax_issue"}
    assert new_types.issubset(VALID_FLAG_TYPES)
    assert len(VALID_FLAG_TYPES) == 17


def test_trust_issue_severity_floor():
    """trust_issue severity must be at least high."""
    flag = _make_flag(flag_type="trust_issue", severity="low")
    result = normalize_flags([flag])
    assert len(result) == 1
    assert result[0]["severity"] == "high"


def test_estate_issue_severity_floor():
    """estate_issue severity must be at least high."""
    flag = _make_flag(flag_type="estate_issue", severity="medium")
    result = normalize_flags([flag])
    assert len(result) == 1
    assert result[0]["severity"] == "high"


def test_mineral_rights_severity_cap():
    """mineral_rights is capped at high."""
    flag = _make_flag(flag_type="mineral_rights", severity="critical")
    result = normalize_flags([flag])
    assert len(result) == 1
    assert result[0]["severity"] == "high"


def test_mineral_rights_severity_cap_does_not_raise():
    """mineral_rights cap should not raise a severity below the cap."""
    flag = _make_flag(flag_type="mineral_rights", severity="low")
    result = normalize_flags([flag])
    assert result[0]["severity"] == "low"


def test_tax_issue_severity_floor():
    """tax_issue severity must be at least medium."""
    flag = _make_flag(flag_type="tax_issue", severity="low")
    result = normalize_flags([flag])
    assert len(result) == 1
    assert result[0]["severity"] == "medium"


def test_vesting_issue_accepted():
    """vesting_issue is a valid flag type and passes normalization."""
    flag = _make_flag(flag_type="vesting_issue", severity="high")
    result = normalize_flags([flag])
    assert len(result) == 1
    assert result[0]["flag_type"] == "vesting_issue"


def test_rules_version_v4():
    """RULES_VERSION is v4 after adding new flag types."""
    assert RULES_VERSION == "flag_rules_v4"
    assert "trust_issue" in SEVERITY_FLOOR
    assert "estate_issue" in SEVERITY_FLOOR
    assert "tax_issue" in SEVERITY_FLOOR
    assert "mineral_rights" in SEVERITY_CAP


# ---------------------------------------------------------------------------
# detect_chain_gaps
# ---------------------------------------------------------------------------


def _make_chain_result_with_gap() -> ChainResult:
    """Build a ChainResult with one gap (score < 30 → critical)."""
    links = [
        ChainLink(1, "Alice", "Bob", None, "D-001", "deed", "", [{"page_number": 1}]),
        ChainLink(2, "Charlie", "Dave", None, "D-002", "deed", "", [{"page_number": 3}]),
    ]
    gap = ChainGap(
        position=1, expected_grantor="Bob", actual_grantor="Charlie",
        match_score=25.0, evidence_refs=[{"page_number": 1}, {"page_number": 3}],
    )
    return ChainResult(links=links, gaps=[gap], unreleased_mortgages=[],
                       chain_complete=False, total_links=2)


def test_detect_chain_gaps_with_gap():
    """Chain gap produces a chain_of_title_gap flag with critical severity."""
    cr = _make_chain_result_with_gap()
    flags = detect_chain_gaps(cr)
    assert len(flags) == 1
    assert flags[0]["flag_type"] == "chain_of_title_gap"
    assert flags[0]["severity"] == "critical"  # score < 30
    assert "Bob" in flags[0]["description"]
    assert "Charlie" in flags[0]["description"]
    assert flags[0]["source"] == "deterministic"


def test_detect_chain_gaps_no_gap():
    """No gaps produces no flags."""
    cr = ChainResult(links=[], gaps=[], unreleased_mortgages=[],
                     chain_complete=True, total_links=2)
    flags = detect_chain_gaps(cr)
    assert len(flags) == 0


def test_detect_chain_gaps_high_severity_above_30():
    """Gap with match_score >= 30 produces high severity."""
    gap = ChainGap(1, "Bob", "Bobby", 55.0, [{"page_number": 1}])
    cr = ChainResult(links=[], gaps=[gap], unreleased_mortgages=[],
                     chain_complete=False, total_links=0)
    flags = detect_chain_gaps(cr)
    assert len(flags) == 1
    assert flags[0]["severity"] == "high"


# ---------------------------------------------------------------------------
# detect_unreleased_mortgages_from_chain
# ---------------------------------------------------------------------------


def test_detect_unreleased_mortgages_found():
    """Mortgage link without release produces unreleased_mortgage flag."""
    mortgage = ChainLink(1, "Alice", "BigBank", None, "MTG-001", "mortgage",
                         "$200,000", [{"page_number": 5}])
    um = UnreleasedMortgage(mortgage_link=mortgage, recording_ref="MTG-001",
                            evidence_refs=[{"page_number": 5}])
    cr = ChainResult(links=[mortgage], gaps=[], unreleased_mortgages=[um],
                     chain_complete=True, total_links=1)
    flags = detect_unreleased_mortgages_from_chain(cr)
    assert len(flags) == 1
    assert flags[0]["flag_type"] == "unreleased_mortgage"
    assert flags[0]["severity"] == "high"
    assert "MTG-001" in flags[0]["title"]
    assert "BigBank" in flags[0]["description"]
    assert flags[0]["source"] == "deterministic"


def test_detect_unreleased_mortgages_none():
    """No unreleased mortgages produces no flags."""
    cr = ChainResult(links=[], gaps=[], unreleased_mortgages=[],
                     chain_complete=True, total_links=0)
    flags = detect_unreleased_mortgages_from_chain(cr)
    assert len(flags) == 0


def test_detect_unreleased_mortgages_no_ref():
    """Unreleased mortgage without recording_ref still generates flag."""
    mortgage = ChainLink(1, "Alice", "BigBank", None, "", "deed of trust",
                         "", [{"page_number": 2}])
    um = UnreleasedMortgage(mortgage_link=mortgage, recording_ref="",
                            evidence_refs=[{"page_number": 2}])
    cr = ChainResult(links=[mortgage], gaps=[], unreleased_mortgages=[um],
                     chain_complete=True, total_links=1)
    flags = detect_unreleased_mortgages_from_chain(cr)
    assert len(flags) == 1
    assert flags[0]["flag_type"] == "unreleased_mortgage"


# ---------------------------------------------------------------------------
# detect_name_discrepancies
# ---------------------------------------------------------------------------


def test_detect_name_discrepancies_near_match():
    """Similar but not identical party names produce a name_discrepancy flag."""
    extractions = [
        {"extraction_type": "party", "value": {"name": "Robert J. Smith", "role": "grantor"},
         "evidence_refs": [{"page_number": 1}]},
        {"extraction_type": "party", "value": {"name": "Robert Smith", "role": "grantor"},
         "evidence_refs": [{"page_number": 3}]},
    ]
    flags = detect_name_discrepancies(extractions)
    assert len(flags) >= 1
    assert all(f["flag_type"] == "name_discrepancy" for f in flags)
    assert all(f["severity"] == "medium" for f in flags)
    assert all(f["source"] == "deterministic" for f in flags)


def test_detect_name_discrepancies_exact_no_flag():
    """Identical party names produce no discrepancy."""
    extractions = [
        {"extraction_type": "party", "value": {"name": "Alice Johnson", "role": "buyer"},
         "evidence_refs": [{"page_number": 1}]},
        {"extraction_type": "party", "value": {"name": "Alice Johnson", "role": "buyer"},
         "evidence_refs": [{"page_number": 2}]},
    ]
    flags = detect_name_discrepancies(extractions)
    assert len(flags) == 0


def test_detect_name_discrepancies_completely_different_no_flag():
    """Completely different names are below threshold — no flag."""
    extractions = [
        {"extraction_type": "party", "value": {"name": "Alice Johnson", "role": "buyer"},
         "evidence_refs": [{"page_number": 1}]},
        {"extraction_type": "party", "value": {"name": "Xerxes Zimmerman", "role": "seller"},
         "evidence_refs": [{"page_number": 2}]},
    ]
    flags = detect_name_discrepancies(extractions)
    assert len(flags) == 0


def test_detect_name_discrepancies_from_chain_of_title():
    """Discrepancies found in chain_of_title extraction grantor/grantee fields."""
    extractions = [
        {"extraction_type": "chain_of_title",
         "value": {"grantor": "Robert J Smith", "grantee": "First National Bank"},
         "evidence_refs": [{"page_number": 2}]},
        {"extraction_type": "chain_of_title",
         "value": {"grantor": "Robert Smith", "grantee": "Second National Bank"},
         "evidence_refs": [{"page_number": 5}]},
    ]
    flags = detect_name_discrepancies(extractions)
    # "Robert J Smith" vs "Robert Smith" — fuzzy near-match (~92%)
    has_smith = any("Smith" in f.get("title", "") or "Smith" in f.get("description", "")
                    for f in flags)
    assert has_smith


# ---------------------------------------------------------------------------
# detect_cross_section_mismatches
# ---------------------------------------------------------------------------


def test_cross_section_property_mismatch():
    """Different property addresses across sections produce a flag."""
    extractions = [
        {"extraction_type": "property", "value": {"address": "123 Main Street, Springfield, IL"},
         "evidence_refs": [{"page_number": 1}]},
        {"extraction_type": "property", "value": {"address": "123 Main St, Springfield, IL"},
         "evidence_refs": [{"page_number": 5}]},
    ]
    sections = [
        {"section_type": "schedule_a", "start_page": 1, "end_page": 3},
        {"section_type": "schedule_b2", "start_page": 4, "end_page": 7},
    ]
    flags = detect_cross_section_mismatches(extractions, sections)
    assert len(flags) >= 1
    assert all(f["flag_type"] == "cross_section_mismatch" for f in flags)
    assert all(f["severity"] == "medium" for f in flags)


def test_cross_section_no_sections_no_flags():
    """Fewer than 2 sections produces no flags."""
    assert detect_cross_section_mismatches([], None) == []
    assert detect_cross_section_mismatches(
        [], [{"section_type": "schedule_a", "start_page": 1, "end_page": 5}]
    ) == []


def test_cross_section_party_name_mismatch():
    """Different party names across sections produce a flag."""
    extractions = [
        {"extraction_type": "party", "value": {"name": "Robert J. Smith"},
         "evidence_refs": [{"page_number": 1}]},
        {"extraction_type": "party", "value": {"name": "Robert Smith"},
         "evidence_refs": [{"page_number": 5}]},
    ]
    sections = [
        {"section_type": "schedule_a", "start_page": 1, "end_page": 3},
        {"section_type": "schedule_b1", "start_page": 4, "end_page": 7},
    ]
    flags = detect_cross_section_mismatches(extractions, sections)
    assert len(flags) >= 1
    assert all(f["flag_type"] == "cross_section_mismatch" for f in flags)


# ---------------------------------------------------------------------------
# generate_deterministic_flags
# ---------------------------------------------------------------------------


def test_generate_deterministic_flags_orchestrates_all():
    """Orchestrator calls all generators and normalizes output."""
    extractions = [
        {"extraction_type": "chain_of_title",
         "value": {"grantor": "Alice", "grantee": "Bob",
                   "recording_date": "2020-01-01", "instrument_type": "deed",
                   "recording_ref": "D-001"},
         "evidence_refs": [{"page_number": 1}]},
        {"extraction_type": "chain_of_title",
         "value": {"grantor": "Charlie", "grantee": "Dave",
                   "recording_date": "2021-01-01", "instrument_type": "deed",
                   "recording_ref": "D-002"},
         "evidence_refs": [{"page_number": 3}]},
        {"extraction_type": "chain_of_title",
         "value": {"grantor": "Dave", "grantee": "BigBank",
                   "recording_date": "2021-06-01", "instrument_type": "mortgage",
                   "recording_ref": "MTG-001"},
         "evidence_refs": [{"page_number": 5}]},
    ]
    flags = generate_deterministic_flags(extractions)
    flag_types = {f["flag_type"] for f in flags}
    assert "chain_of_title_gap" in flag_types
    assert "unreleased_mortgage" in flag_types
    for f in flags:
        assert f["flag_type"] in VALID_FLAG_TYPES


def test_generate_deterministic_flags_empty_input():
    """No extractions produces no deterministic flags."""
    flags = generate_deterministic_flags([])
    assert flags == []


# ---------------------------------------------------------------------------
# merge_llm_and_deterministic_flags
# ---------------------------------------------------------------------------


def test_merge_replaces_deterministic_types():
    """LLM flags for deterministic types are replaced by rules engine output."""
    llm_flags = [
        {"flag_type": "chain_of_title_gap", "severity": "medium",
         "title": "LLM Gap", "description": "LLM detected gap",
         "evidence_refs": [{"page_number": 1}]},
        {"flag_type": "unresolved_lien", "severity": "high",
         "title": "Lien found", "description": "Unresolved lien",
         "evidence_refs": [{"page_number": 2}]},
    ]
    det_flags = [
        {"flag_type": "chain_of_title_gap", "severity": "high",
         "title": "Rules Gap", "description": "Rules-detected gap",
         "evidence_refs": [{"page_number": 1}]},
    ]
    merged = merge_llm_and_deterministic_flags(llm_flags, det_flags)
    gap_flags = [f for f in merged if f["flag_type"] == "chain_of_title_gap"]
    assert len(gap_flags) == 1
    assert gap_flags[0]["title"] == "Rules Gap"
    lien_flags = [f for f in merged if f["flag_type"] == "unresolved_lien"]
    assert len(lien_flags) == 1


def test_merge_keeps_non_deterministic_llm_flags():
    """LLM flags for non-deterministic types are preserved."""
    llm_flags = [
        {"flag_type": "missing_endorsement", "severity": "medium",
         "title": "Missing ALTA 5", "description": "No ALTA 5",
         "evidence_refs": [{"page_number": 8}]},
        {"flag_type": "regulatory_compliance", "severity": "low",
         "title": "FinCEN flag", "description": "Compliance check needed",
         "evidence_refs": [{"page_number": 10}]},
    ]
    merged = merge_llm_and_deterministic_flags(llm_flags, [])
    assert len(merged) == 2


def test_merge_drops_all_llm_for_all_deterministic_types():
    """ALL 4 deterministic flag types from LLM are dropped."""
    llm_flags = [
        {"flag_type": ft, "severity": "medium", "title": f"LLM {ft}",
         "description": f"LLM detected {ft}", "evidence_refs": [{"page_number": 1}]}
        for ft in DETERMINISTIC_FLAG_TYPES
    ]
    merged = merge_llm_and_deterministic_flags(llm_flags, [])
    assert len(merged) == 0


# ---------------------------------------------------------------------------
# Determinism: same inputs → identical outputs across N runs
# ---------------------------------------------------------------------------


def test_generate_deterministic_flags_10_runs():
    """generate_deterministic_flags 10x → identical output every time."""
    extractions = [
        {"extraction_type": "chain_of_title",
         "value": {"grantor": "Alice", "grantee": "Bob",
                   "recording_date": "2020-01-01", "instrument_type": "deed",
                   "recording_ref": "D-001"},
         "evidence_refs": [{"page_number": 1}]},
        {"extraction_type": "chain_of_title",
         "value": {"grantor": "Charlie", "grantee": "Dave",
                   "recording_date": "2021-01-01", "instrument_type": "deed",
                   "recording_ref": "D-002"},
         "evidence_refs": [{"page_number": 3}]},
        {"extraction_type": "chain_of_title",
         "value": {"grantor": "Dave", "grantee": "BigBank",
                   "recording_date": "2021-06-01", "instrument_type": "mortgage",
                   "recording_ref": "MTG-001"},
         "evidence_refs": [{"page_number": 5}]},
    ]
    results = [generate_deterministic_flags(copy.deepcopy(extractions)) for _ in range(10)]
    first = results[0]
    for r in results[1:]:
        assert len(r) == len(first)
        for f1, f2 in zip(first, r):
            assert f1["flag_type"] == f2["flag_type"]
            assert f1["severity"] == f2["severity"]
            assert f1["title"] == f2["title"]
            assert f1["description"] == f2["description"]
