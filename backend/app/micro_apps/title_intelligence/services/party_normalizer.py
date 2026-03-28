"""Deterministic party name normalization and fuzzy matching.

Normalizes party names (individuals and entities) for consistent comparison
across extractions. Uses rapidfuzz for fuzzy matching with exact-only fallback.

Version changes MUST bump NORMALIZER_VERSION so cache keys stay auditable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

NORMALIZER_VERSION = "party_norm_v1"

# Suffixes to strip from individual names
_INDIVIDUAL_SUFFIXES = re.compile(
    r",?\s*\b(Jr\.?|Sr\.?|III|II|IV|Esq\.?|Ph\.?D\.?|M\.?D\.?)\b\.?\s*$",
    re.IGNORECASE,
)

# Suffixes to strip from entity names
_ENTITY_SUFFIXES = re.compile(
    r",?\s*\b(LLC|L\.L\.C\.?|Inc\.?|Corp\.?|Corporation|Ltd\.?|Limited|"
    r"LP|L\.P\.?|LLP|L\.L\.P\.?|Trust|Co\.?|Company|NA|N\.A\.?|"
    r"Association|Assoc\.?|Foundation|Partners|Partnership)\b\.?\s*$",
    re.IGNORECASE,
)

# Patterns that indicate an entity (not an individual)
_ENTITY_INDICATORS = re.compile(
    r"\b(LLC|L\.L\.C|Inc|Corp|Corporation|Ltd|Limited|LP|L\.P|LLP|L\.L\.P|"
    r"Trust|Co\b|Company|NA|N\.A|Association|Assoc|Foundation|Partners|"
    r"Partnership|Bank|Savings|Federal|National|Mortgage|Title|Insurance|"
    r"Lending|Financial|Holdings|Group|Services|Properties|Investments|"
    r"Development|Construction|Realty|Real\s+Estate)\b",
    re.IGNORECASE,
)

# Common noise words to remove
_NOISE_WORDS = frozenset({
    "a", "an", "the", "and", "of", "as", "aka", "fka", "nka",
    "formerly", "known", "now",
})


@dataclass(frozen=True)
class NormalizedParty:
    """Result of normalizing a party name."""

    original: str
    normalized: str
    is_entity: bool
    canonical_tokens: tuple[str, ...]


@dataclass(frozen=True)
class PartyMatch:
    """Result of comparing two party names."""

    party_a: str
    party_b: str
    score: float
    is_match: bool
    match_method: str  # "exact", "fuzzy", or "no_match"


def _is_entity(name: str) -> bool:
    """Detect whether a name refers to an entity (vs. individual)."""
    return bool(_ENTITY_INDICATORS.search(name))


def normalize_party_name(name: str) -> NormalizedParty:
    """Normalize a party name for comparison.

    Steps:
    1. Case-fold to lowercase
    2. Detect entity vs. individual
    3. Strip suffixes (Jr/Sr/III for individuals; LLC/Inc/Trust for entities)
    4. Remove noise words (a, an, the, aka, fka, etc.)
    5. Collapse whitespace and strip punctuation
    6. Sort tokens for order-independent comparison
    """
    if not name or not name.strip():
        return NormalizedParty(
            original=name,
            normalized="",
            is_entity=False,
            canonical_tokens=(),
        )

    original = name.strip()
    is_entity = _is_entity(original)
    working = original.lower()

    # Strip entity/individual suffixes (may need multiple passes)
    suffix_re = _ENTITY_SUFFIXES if is_entity else _INDIVIDUAL_SUFFIXES
    for _ in range(3):
        prev = working
        working = suffix_re.sub("", working).strip()
        if working == prev:
            break

    # Remove punctuation except hyphens (keep hyphenated names)
    working = re.sub(r"[^\w\s-]", " ", working)

    # Collapse whitespace
    working = re.sub(r"\s+", " ", working).strip()

    # Tokenize and remove noise words
    tokens = [t for t in working.split() if t not in _NOISE_WORDS]

    # Sort for order-independent comparison
    canonical = tuple(sorted(tokens))

    normalized = " ".join(canonical)

    return NormalizedParty(
        original=original,
        normalized=normalized,
        is_entity=is_entity,
        canonical_tokens=canonical,
    )


def match_parties(a: str, b: str, threshold: float = 85.0) -> PartyMatch:
    """Compare two party names for equivalence.

    First tries exact token match (after normalization), then falls back
    to rapidfuzz token_sort_ratio for fuzzy matching.

    Args:
        a: First party name
        b: Second party name
        threshold: Minimum fuzzy score (0-100) to consider a match

    Returns:
        PartyMatch with score and match status
    """
    norm_a = normalize_party_name(a)
    norm_b = normalize_party_name(b)

    # Empty names never match
    if not norm_a.normalized or not norm_b.normalized:
        return PartyMatch(a, b, 0.0, False, "no_match")

    # Exact token match
    if norm_a.canonical_tokens == norm_b.canonical_tokens:
        return PartyMatch(a, b, 100.0, True, "exact")

    # Fuzzy match via rapidfuzz
    score = _fuzzy_score(norm_a.normalized, norm_b.normalized)
    if score >= threshold:
        return PartyMatch(a, b, score, True, "fuzzy")

    return PartyMatch(a, b, score, False, "no_match")


def _fuzzy_score(a: str, b: str) -> float:
    """Compute fuzzy similarity score between two normalized strings."""
    try:
        from rapidfuzz.fuzz import token_sort_ratio
        return token_sort_ratio(a, b)
    except ImportError:
        # Fallback: simple token overlap ratio
        tokens_a = set(a.split())
        tokens_b = set(b.split())
        if not tokens_a or not tokens_b:
            return 0.0
        overlap = len(tokens_a & tokens_b)
        total = max(len(tokens_a), len(tokens_b))
        return (overlap / total) * 100.0


def find_name_discrepancies(
    extractions: list[dict],
    threshold: float = 85.0,
) -> list[dict]:
    """Find party name discrepancies across extractions.

    Collects all party names from 'party' and 'chain_of_title' extractions,
    groups by role, and does pairwise comparison. Returns flags for names
    that are similar but not identical (score in [threshold, 100) range).

    Args:
        extractions: List of extraction dicts with extraction_type, label, value
        threshold: Fuzzy match threshold

    Returns:
        List of discrepancy dicts with flag metadata
    """
    # Collect party names with their sources
    party_entries: list[dict] = []

    for ext in extractions:
        ext_type = ext.get("extraction_type", "")
        value = ext.get("value") or {}
        evidence = ext.get("evidence_refs") or []

        if ext_type == "party":
            name = value.get("name", "")
            if name:
                party_entries.append({
                    "name": name,
                    "role": value.get("role", "unknown"),
                    "source": "party_extraction",
                    "evidence_refs": evidence,
                })
        elif ext_type == "chain_of_title":
            for key in ("grantor", "from", "from_party"):
                name = value.get(key, "")
                if name:
                    party_entries.append({
                        "name": name,
                        "role": "grantor",
                        "source": "chain_of_title",
                        "evidence_refs": evidence,
                    })
            for key in ("grantee", "to", "to_party"):
                name = value.get(key, "")
                if name:
                    party_entries.append({
                        "name": name,
                        "role": "grantee",
                        "source": "chain_of_title",
                        "evidence_refs": evidence,
                    })

    if len(party_entries) < 2:
        return []

    # Pairwise comparison — only flag near-matches (not exact matches)
    discrepancies: list[dict] = []
    seen_pairs: set[tuple[str, str]] = set()

    for i, entry_a in enumerate(party_entries):
        for entry_b in party_entries[i + 1:]:
            name_a = entry_a["name"]
            name_b = entry_b["name"]

            # Deterministic pair key to avoid duplicates
            pair_key = tuple(sorted([name_a.lower(), name_b.lower()]))
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)

            result = match_parties(name_a, name_b, threshold=threshold)

            # We want near-matches: similar but not identical
            if result.is_match and result.score < 100.0:
                # Combine evidence refs from both entries
                combined_refs = []
                seen_ref_keys: set[tuple] = set()
                for ref in entry_a["evidence_refs"] + entry_b["evidence_refs"]:
                    ref_key = (ref.get("page_number"), ref.get("text_snippet", "")[:50])
                    if ref_key not in seen_ref_keys:
                        combined_refs.append(ref)
                        seen_ref_keys.add(ref_key)

                discrepancies.append({
                    "name_a": name_a,
                    "name_b": name_b,
                    "score": result.score,
                    "match_method": result.match_method,
                    "role_a": entry_a["role"],
                    "role_b": entry_b["role"],
                    "evidence_refs": combined_refs,
                })

    return discrepancies
