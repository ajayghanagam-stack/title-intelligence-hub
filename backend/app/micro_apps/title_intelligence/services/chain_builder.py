"""Deterministic chain-of-title builder from structured extractions.

Parses chain_of_title extractions into a linked chain, detects gaps
(grantor/grantee mismatches between successive links), and identifies
unreleased mortgages (encumbrances without matching releases).

Version changes MUST bump CHAIN_BUILDER_VERSION so cache keys stay auditable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.micro_apps.title_intelligence.services.party_normalizer import match_parties

CHAIN_BUILDER_VERSION = "chain_builder_v1"


@dataclass
class ChainLink:
    """A single link in the chain of title."""

    position: int
    grantor: str
    grantee: str
    recording_date: date | None
    recording_ref: str
    instrument_type: str
    amount: str
    evidence_refs: list[dict] = field(default_factory=list)


@dataclass
class ChainGap:
    """A detected gap in the chain of title."""

    position: int  # position after which the gap occurs
    expected_grantor: str  # grantee of the previous link (expected to be next grantor)
    actual_grantor: str  # actual grantor of the next link
    match_score: float
    evidence_refs: list[dict] = field(default_factory=list)


@dataclass
class UnreleasedMortgage:
    """A mortgage/DOT without a matching release."""

    mortgage_link: ChainLink
    recording_ref: str
    evidence_refs: list[dict] = field(default_factory=list)


@dataclass
class ChainResult:
    """Complete chain analysis result."""

    links: list[ChainLink] = field(default_factory=list)
    gaps: list[ChainGap] = field(default_factory=list)
    unreleased_mortgages: list[UnreleasedMortgage] = field(default_factory=list)
    chain_complete: bool = True
    total_links: int = 0


# Instrument types considered encumbrances (need releases)
_ENCUMBRANCE_TYPES = frozenset({
    "mortgage", "deed of trust", "dot", "deed_of_trust",
    "security instrument", "home equity loan",
})

# Instrument types considered releases
_RELEASE_TYPES = frozenset({
    "release", "satisfaction", "reconveyance", "discharge",
    "release of mortgage", "satisfaction of mortgage",
    "full reconveyance", "deed of reconveyance",
    "release of deed of trust", "payoff",
})

# Key aliases for grantor/grantee in extraction values
_GRANTOR_KEYS = ("grantor", "from", "from_party", "seller", "borrower")
_GRANTEE_KEYS = ("grantee", "to", "to_party", "buyer", "lender")


def _get_first(d: dict, keys: tuple[str, ...], default: str = "") -> str:
    """Get the first non-empty value from a dict by trying multiple keys."""
    for key in keys:
        val = d.get(key, "")
        if val and str(val).strip():
            return str(val).strip()
    return default


def _parse_date(value: Any) -> date | None:
    """Parse a date from various string formats."""
    if value is None:
        return None
    if isinstance(value, date):
        return value
    s = str(value).strip()
    if not s:
        return None
    # Try common formats
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%B %d, %Y", "%b %d, %Y"):
        try:
            from datetime import datetime
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _normalize_instrument_type(raw: str) -> str:
    """Normalize instrument type to lowercase, trimmed form."""
    return re.sub(r"\s+", " ", raw.strip().lower()) if raw else ""


def _is_encumbrance(instrument_type: str) -> bool:
    """Check if an instrument type represents an encumbrance."""
    normalized = _normalize_instrument_type(instrument_type)
    return normalized in _ENCUMBRANCE_TYPES or "mortgage" in normalized or "deed of trust" in normalized


def _is_release(instrument_type: str) -> bool:
    """Check if an instrument type represents a release."""
    normalized = _normalize_instrument_type(instrument_type)
    return normalized in _RELEASE_TYPES or "release" in normalized or "satisfaction" in normalized or "reconveyance" in normalized


def build_chain(extractions: list[dict], threshold: float = 85.0) -> ChainResult:
    """Build a chain of title from extractions and detect gaps/unreleased mortgages.

    Args:
        extractions: List of extraction dicts from the examiner
        threshold: Fuzzy match threshold for party name comparison

    Returns:
        ChainResult with links, gaps, and unreleased mortgages
    """
    # Filter to chain_of_title extractions
    chain_extractions = [
        e for e in extractions
        if e.get("extraction_type") == "chain_of_title"
    ]

    if not chain_extractions:
        return ChainResult()

    # Parse into ChainLinks
    links: list[ChainLink] = []
    for ext in chain_extractions:
        value = ext.get("value") or {}
        evidence = ext.get("evidence_refs") or []

        grantor = _get_first(value, _GRANTOR_KEYS)
        grantee = _get_first(value, _GRANTEE_KEYS)

        if not grantor and not grantee:
            continue

        recording_date = _parse_date(
            value.get("recording_date") or value.get("date") or value.get("recorded_date")
        )
        recording_ref = str(
            value.get("recording_ref", "") or value.get("recording_number", "")
            or value.get("instrument_number", "") or value.get("book_page", "")
        ).strip()
        instrument_type = str(value.get("instrument_type", "") or value.get("type", "")).strip()
        amount = str(value.get("amount", "") or value.get("consideration", "")).strip()

        links.append(ChainLink(
            position=0,  # will be assigned after sorting
            grantor=grantor,
            grantee=grantee,
            recording_date=recording_date,
            recording_ref=recording_ref,
            instrument_type=instrument_type,
            amount=amount,
            evidence_refs=list(evidence),
        ))

    if not links:
        return ChainResult()

    # Sort chronologically (None dates to end)
    links.sort(key=lambda l: (l.recording_date is None, l.recording_date or date.max))

    # Assign positions
    for i, link in enumerate(links):
        link.position = i + 1

    # Detect gaps: walk conveyance links, check grantee[i] matches grantor[i+1]
    # Only conveyance-type links participate in gap detection
    conveyance_links = [
        l for l in links
        if not _is_encumbrance(l.instrument_type) and not _is_release(l.instrument_type)
    ]

    gaps: list[ChainGap] = []
    for i in range(len(conveyance_links) - 1):
        current = conveyance_links[i]
        next_link = conveyance_links[i + 1]

        if not current.grantee or not next_link.grantor:
            continue

        result = match_parties(current.grantee, next_link.grantor, threshold=threshold)

        if not result.is_match:
            # Combine evidence refs
            combined_refs = list(current.evidence_refs) + list(next_link.evidence_refs)
            gaps.append(ChainGap(
                position=current.position,
                expected_grantor=current.grantee,
                actual_grantor=next_link.grantor,
                match_score=result.score,
                evidence_refs=combined_refs,
            ))

    # Detect unreleased mortgages
    encumbrances = [l for l in links if _is_encumbrance(l.instrument_type)]
    releases = [l for l in links if _is_release(l.instrument_type)]

    unreleased: list[UnreleasedMortgage] = []
    for enc in encumbrances:
        matched = False

        # Try matching by recording_ref first
        if enc.recording_ref:
            for rel in releases:
                rel_value_refs = []
                # Check if the release references this mortgage
                if rel.recording_ref and enc.recording_ref.lower() == rel.recording_ref.lower():
                    matched = True
                    break

        # Fallback: match by party names (grantee of mortgage = grantor of release)
        if not matched and enc.grantee:
            for rel in releases:
                if rel.grantor:
                    party_match = match_parties(enc.grantee, rel.grantor, threshold=threshold)
                    if party_match.is_match:
                        matched = True
                        break

        if not matched:
            unreleased.append(UnreleasedMortgage(
                mortgage_link=enc,
                recording_ref=enc.recording_ref,
                evidence_refs=list(enc.evidence_refs),
            ))

    chain_complete = len(gaps) == 0

    return ChainResult(
        links=links,
        gaps=gaps,
        unreleased_mortgages=unreleased,
        chain_complete=chain_complete,
        total_links=len(links),
    )
