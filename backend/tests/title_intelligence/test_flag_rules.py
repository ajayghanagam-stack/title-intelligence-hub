"""Tests for the deterministic flag rule engine."""

import pytest

from app.micro_apps.title_intelligence.services.flag_rules import (
    RULES_VERSION,
    VALID_FLAG_TYPES,
    VALID_SEVERITIES,
    normalize_flags,
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
    assert RULES_VERSION == "flag_rules_v1"


# --- Input not mutated ---

def test_input_not_mutated():
    """normalize_flags should not mutate the input list."""
    original = [_make_flag(flag_type="unresolved_lien", severity="low")]
    import copy
    snapshot = copy.deepcopy(original)
    normalize_flags(original)
    assert original == snapshot
