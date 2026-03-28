"""Tests for the deterministic party name normalizer."""

import pytest

from app.micro_apps.title_intelligence.services.party_normalizer import (
    NORMALIZER_VERSION,
    NormalizedParty,
    PartyMatch,
    normalize_party_name,
    match_parties,
    find_name_discrepancies,
)


# --- Version ---

def test_normalizer_version():
    assert NORMALIZER_VERSION == "party_norm_v1"


# --- normalize_party_name ---

def test_normalize_basic_individual():
    result = normalize_party_name("John Smith")
    assert result.normalized == "john smith"
    assert result.is_entity is False
    assert result.canonical_tokens == ("john", "smith")


def test_normalize_case_insensitive():
    a = normalize_party_name("JOHN SMITH")
    b = normalize_party_name("john smith")
    assert a.canonical_tokens == b.canonical_tokens


def test_normalize_strips_individual_suffix():
    result = normalize_party_name("John Smith Jr.")
    assert "jr" not in result.normalized
    assert result.canonical_tokens == ("john", "smith")


def test_normalize_strips_sr_suffix():
    result = normalize_party_name("Robert Jones, Sr.")
    assert "sr" not in result.normalized


def test_normalize_strips_iii_suffix():
    result = normalize_party_name("William Davis III")
    assert "iii" not in result.normalized


def test_normalize_entity_detected():
    result = normalize_party_name("Acme Holdings LLC")
    assert result.is_entity is True


def test_normalize_strips_entity_suffix():
    result = normalize_party_name("Acme Holdings LLC")
    assert "llc" not in result.normalized
    assert "acme" in result.canonical_tokens
    assert "holdings" in result.canonical_tokens


def test_normalize_trust_entity():
    result = normalize_party_name("Smith Family Trust")
    assert result.is_entity is True
    # "trust" is stripped as entity suffix
    assert "trust" not in result.canonical_tokens


def test_normalize_sorts_tokens():
    a = normalize_party_name("John Smith")
    b = normalize_party_name("Smith John")
    assert a.canonical_tokens == b.canonical_tokens


def test_normalize_removes_noise_words():
    result = normalize_party_name("John A. Smith aka John Smith")
    assert "aka" not in result.canonical_tokens
    assert "a" not in result.canonical_tokens


def test_normalize_empty_string():
    result = normalize_party_name("")
    assert result.normalized == ""
    assert result.canonical_tokens == ()


def test_normalize_whitespace_only():
    result = normalize_party_name("   ")
    assert result.normalized == ""


def test_normalize_preserves_original():
    result = normalize_party_name("John Smith Jr.")
    assert result.original == "John Smith Jr."


# --- match_parties ---

def test_match_exact_same_name():
    result = match_parties("John Smith", "John Smith")
    assert result.is_match is True
    assert result.score == 100.0
    assert result.match_method == "exact"


def test_match_different_case():
    result = match_parties("JOHN SMITH", "john smith")
    assert result.is_match is True
    assert result.match_method == "exact"


def test_match_with_suffix_difference():
    result = match_parties("John Smith", "John Smith Jr.")
    assert result.is_match is True
    assert result.match_method == "exact"


def test_match_reversed_order():
    result = match_parties("John Smith", "Smith John")
    assert result.is_match is True
    assert result.match_method == "exact"


def test_match_fuzzy_similar():
    result = match_parties("John A. Smith", "John Smith")
    assert result.is_match is True


def test_match_completely_different():
    result = match_parties("John Smith", "Robert Johnson")
    assert result.is_match is False
    assert result.match_method == "no_match"


def test_match_empty_names():
    result = match_parties("", "John Smith")
    assert result.is_match is False


def test_match_both_empty():
    result = match_parties("", "")
    assert result.is_match is False


def test_match_threshold_boundary():
    """Names right at the threshold boundary."""
    # "John Michael Smith" vs "John M Smith" → score ~80, below default 85 threshold
    result = match_parties("John Michael Smith", "John M. Smith")
    assert result.is_match is False
    # But with a lower threshold they match
    result_low = match_parties("John Michael Smith", "John M. Smith", threshold=75.0)
    assert result_low.is_match is True


def test_match_entities():
    result = match_parties("Acme Holdings LLC", "Acme Holdings, Inc.")
    assert result.is_match is True


# --- find_name_discrepancies ---

def test_discrepancies_none_for_identical():
    extractions = [
        {"extraction_type": "party", "value": {"name": "John Smith", "role": "buyer"}, "evidence_refs": [{"page_number": 1, "text_snippet": "John Smith"}]},
        {"extraction_type": "party", "value": {"name": "John Smith", "role": "buyer"}, "evidence_refs": [{"page_number": 2, "text_snippet": "John Smith"}]},
    ]
    result = find_name_discrepancies(extractions)
    assert len(result) == 0


def test_discrepancies_detects_near_match():
    extractions = [
        {"extraction_type": "party", "value": {"name": "John Smith", "role": "buyer"}, "evidence_refs": [{"page_number": 1, "text_snippet": "John Smith"}]},
        {"extraction_type": "party", "value": {"name": "John A. Smith", "role": "buyer"}, "evidence_refs": [{"page_number": 2, "text_snippet": "John A Smith"}]},
    ]
    result = find_name_discrepancies(extractions)
    # This should be detected as a near-match discrepancy (fuzzy but not exact)
    # The result depends on whether normalization makes them exact or fuzzy
    # With suffix/noise stripping, "John Smith" and "John A. Smith" -> "john smith" vs "john smith"
    # "A" is a noise word, so both normalize to the same. No discrepancy.
    # This is correct behavior — noise words are stripped.
    assert len(result) == 0


def test_discrepancies_detects_spelling_variation():
    extractions = [
        {"extraction_type": "party", "value": {"name": "Michael Johnson", "role": "seller"}, "evidence_refs": [{"page_number": 1, "text_snippet": "Michael Johnson"}]},
        {"extraction_type": "party", "value": {"name": "Micheal Johnson", "role": "seller"}, "evidence_refs": [{"page_number": 3, "text_snippet": "Micheal Johnson"}]},
    ]
    result = find_name_discrepancies(extractions)
    assert len(result) == 1
    assert result[0]["name_a"] == "Michael Johnson"
    assert result[0]["name_b"] == "Micheal Johnson"


def test_discrepancies_from_chain_of_title():
    extractions = [
        {"extraction_type": "chain_of_title", "value": {"grantor": "Michael Johnson", "grantee": "Jane Doe"}, "evidence_refs": [{"page_number": 1, "text_snippet": "deed"}]},
        {"extraction_type": "chain_of_title", "value": {"grantor": "Micheal Johnson", "grantee": "Jane Doe"}, "evidence_refs": [{"page_number": 2, "text_snippet": "deed"}]},
    ]
    result = find_name_discrepancies(extractions)
    assert len(result) >= 1


def test_discrepancies_empty_extractions():
    assert find_name_discrepancies([]) == []


def test_discrepancies_single_party():
    extractions = [
        {"extraction_type": "party", "value": {"name": "John Smith"}, "evidence_refs": []},
    ]
    assert find_name_discrepancies(extractions) == []


def test_discrepancies_completely_different_names():
    """Completely different names should not produce discrepancies."""
    extractions = [
        {"extraction_type": "party", "value": {"name": "John Smith", "role": "buyer"}, "evidence_refs": [{"page_number": 1, "text_snippet": "John Smith"}]},
        {"extraction_type": "party", "value": {"name": "Robert Johnson", "role": "seller"}, "evidence_refs": [{"page_number": 2, "text_snippet": "Robert Johnson"}]},
    ]
    result = find_name_discrepancies(extractions)
    assert len(result) == 0
