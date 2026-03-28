"""Tests for the deterministic chain-of-title builder."""

import pytest

from app.micro_apps.title_intelligence.services.chain_builder import (
    CHAIN_BUILDER_VERSION,
    ChainResult,
    build_chain,
)


def _chain_ext(
    grantor: str = "Alice",
    grantee: str = "Bob",
    recording_date: str | None = "2020-01-01",
    recording_ref: str = "",
    instrument_type: str = "deed",
    amount: str = "",
    page: int = 1,
) -> dict:
    """Helper to create a chain_of_title extraction dict."""
    return {
        "extraction_type": "chain_of_title",
        "label": f"{instrument_type}: {grantor} to {grantee}",
        "value": {
            "grantor": grantor,
            "grantee": grantee,
            "recording_date": recording_date,
            "recording_ref": recording_ref,
            "instrument_type": instrument_type,
            "amount": amount,
        },
        "evidence_refs": [{"page_number": page, "text_snippet": f"evidence on page {page}"}],
    }


# --- Version ---

def test_chain_builder_version():
    assert CHAIN_BUILDER_VERSION == "chain_builder_v1"


# --- Empty / single-link ---

def test_empty_extractions():
    result = build_chain([])
    assert result.links == []
    assert result.gaps == []
    assert result.unreleased_mortgages == []
    assert result.chain_complete is True
    assert result.total_links == 0


def test_non_chain_extractions_ignored():
    extractions = [
        {"extraction_type": "party", "value": {"name": "Alice"}, "evidence_refs": []},
        {"extraction_type": "property", "value": {"address": "123 Main"}, "evidence_refs": []},
    ]
    result = build_chain(extractions)
    assert result.total_links == 0


def test_single_link():
    extractions = [_chain_ext(grantor="Alice", grantee="Bob")]
    result = build_chain(extractions)
    assert result.total_links == 1
    assert result.chain_complete is True
    assert result.gaps == []
    assert result.links[0].grantor == "Alice"
    assert result.links[0].grantee == "Bob"


# --- Simple chain (no gaps) ---

def test_complete_chain():
    extractions = [
        _chain_ext(grantor="Alice", grantee="Bob", recording_date="2020-01-01", page=1),
        _chain_ext(grantor="Bob", grantee="Charlie", recording_date="2021-06-15", page=2),
        _chain_ext(grantor="Charlie", grantee="David", recording_date="2022-03-20", page=3),
    ]
    result = build_chain(extractions)
    assert result.total_links == 3
    assert result.chain_complete is True
    assert result.gaps == []
    # Verify chronological ordering
    assert result.links[0].grantor == "Alice"
    assert result.links[1].grantor == "Bob"
    assert result.links[2].grantor == "Charlie"


# --- Gap detection ---

def test_gap_detected():
    extractions = [
        _chain_ext(grantor="Alice", grantee="Bob", recording_date="2020-01-01", page=1),
        _chain_ext(grantor="Charlie", grantee="David", recording_date="2021-01-01", page=2),
    ]
    result = build_chain(extractions)
    assert result.chain_complete is False
    assert len(result.gaps) == 1
    assert result.gaps[0].expected_grantor == "Bob"
    assert result.gaps[0].actual_grantor == "Charlie"


def test_gap_with_fuzzy_match():
    """Names that are similar but not matching (below threshold) produce a gap."""
    extractions = [
        _chain_ext(grantor="Alice", grantee="Robert Johnson", recording_date="2020-01-01"),
        _chain_ext(grantor="Bob Smith", grantee="Charlie", recording_date="2021-01-01"),
    ]
    result = build_chain(extractions)
    assert result.chain_complete is False
    assert len(result.gaps) == 1


def test_no_gap_with_name_variation():
    """Names that are variations of the same person should not produce a gap."""
    extractions = [
        _chain_ext(grantor="Alice", grantee="Robert Johnson Jr.", recording_date="2020-01-01"),
        _chain_ext(grantor="Robert Johnson", grantee="Charlie", recording_date="2021-01-01"),
    ]
    result = build_chain(extractions)
    assert result.chain_complete is True
    assert len(result.gaps) == 0


# --- Date sorting ---

def test_chronological_sorting():
    extractions = [
        _chain_ext(grantor="Charlie", grantee="David", recording_date="2022-01-01"),
        _chain_ext(grantor="Alice", grantee="Bob", recording_date="2020-01-01"),
        _chain_ext(grantor="Bob", grantee="Charlie", recording_date="2021-01-01"),
    ]
    result = build_chain(extractions)
    assert result.links[0].grantor == "Alice"
    assert result.links[1].grantor == "Bob"
    assert result.links[2].grantor == "Charlie"


def test_none_dates_sorted_to_end():
    extractions = [
        _chain_ext(grantor="Unknown", grantee="Alice", recording_date=None),
        _chain_ext(grantor="Alice", grantee="Bob", recording_date="2020-01-01"),
    ]
    result = build_chain(extractions)
    assert result.links[0].grantor == "Alice"
    assert result.links[1].grantor == "Unknown"


# --- Key variations ---

def test_from_to_keys():
    """Handles 'from'/'to' key variations."""
    extractions = [{
        "extraction_type": "chain_of_title",
        "label": "deed",
        "value": {"from": "Alice", "to": "Bob", "recording_date": "2020-01-01"},
        "evidence_refs": [{"page_number": 1, "text_snippet": "deed"}],
    }]
    result = build_chain(extractions)
    assert result.total_links == 1
    assert result.links[0].grantor == "Alice"
    assert result.links[0].grantee == "Bob"


def test_from_party_to_party_keys():
    """Handles 'from_party'/'to_party' key variations."""
    extractions = [{
        "extraction_type": "chain_of_title",
        "label": "deed",
        "value": {"from_party": "Alice", "to_party": "Bob", "date": "2020-01-01"},
        "evidence_refs": [{"page_number": 1, "text_snippet": "deed"}],
    }]
    result = build_chain(extractions)
    assert result.total_links == 1
    assert result.links[0].grantor == "Alice"


# --- Unreleased mortgages ---

def test_unreleased_mortgage_detected():
    extractions = [
        _chain_ext(grantor="Alice", grantee="Bob", recording_date="2020-01-01", instrument_type="deed"),
        _chain_ext(grantor="Bob", grantee="First Bank", recording_date="2020-02-01", instrument_type="mortgage", recording_ref="2020-12345"),
    ]
    result = build_chain(extractions)
    assert len(result.unreleased_mortgages) == 1
    assert result.unreleased_mortgages[0].recording_ref == "2020-12345"


def test_released_mortgage_not_flagged():
    extractions = [
        _chain_ext(grantor="Bob", grantee="First Bank", recording_date="2020-02-01", instrument_type="mortgage", recording_ref="2020-12345"),
        _chain_ext(grantor="First Bank", grantee="Bob", recording_date="2022-01-01", instrument_type="release", recording_ref="2020-12345"),
    ]
    result = build_chain(extractions)
    assert len(result.unreleased_mortgages) == 0


def test_released_mortgage_by_party_name():
    """Mortgage matched to release by party name when recording_ref differs."""
    extractions = [
        _chain_ext(grantor="Bob", grantee="First National Bank", recording_date="2020-02-01", instrument_type="deed of trust"),
        _chain_ext(grantor="First National Bank", grantee="Bob", recording_date="2022-01-01", instrument_type="reconveyance"),
    ]
    result = build_chain(extractions)
    assert len(result.unreleased_mortgages) == 0


def test_multiple_mortgages_one_unreleased():
    extractions = [
        _chain_ext(grantor="Bob", grantee="Bank A", recording_date="2020-01-01", instrument_type="mortgage", recording_ref="A-001"),
        _chain_ext(grantor="Bank A", grantee="Bob", recording_date="2021-01-01", instrument_type="satisfaction", recording_ref="A-001"),
        _chain_ext(grantor="Bob", grantee="Bank B", recording_date="2022-01-01", instrument_type="mortgage", recording_ref="B-001"),
    ]
    result = build_chain(extractions)
    assert len(result.unreleased_mortgages) == 1
    assert result.unreleased_mortgages[0].recording_ref == "B-001"


# --- Encumbrances don't affect gap detection ---

def test_mortgage_excluded_from_gap_detection():
    """Mortgages should not be part of conveyance chain gap analysis."""
    extractions = [
        _chain_ext(grantor="Alice", grantee="Bob", recording_date="2020-01-01", instrument_type="deed"),
        _chain_ext(grantor="Bob", grantee="Bank", recording_date="2020-06-01", instrument_type="mortgage"),
        _chain_ext(grantor="Bob", grantee="Charlie", recording_date="2021-01-01", instrument_type="deed"),
    ]
    result = build_chain(extractions)
    assert result.chain_complete is True
    assert len(result.gaps) == 0


# --- Missing grantor/grantee ---

def test_extraction_without_names_skipped():
    extractions = [{
        "extraction_type": "chain_of_title",
        "label": "unknown",
        "value": {"recording_date": "2020-01-01"},
        "evidence_refs": [],
    }]
    result = build_chain(extractions)
    assert result.total_links == 0
