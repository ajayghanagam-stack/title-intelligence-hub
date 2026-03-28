"""Deterministic post-processing rules for AI-generated risk flags.

Normalizes, validates, and deduplicates LLM-generated flags so that the same
document inputs produce identical flag output regardless of LLM temperature
variation.  Inserted into the pipeline after the RiskAgent LLM call and before
the DB commit.

Also provides deterministic flag generators that compute certain flag types
directly from structured extractions without LLM reasoning. These replace
LLM-generated flags for covered types, achieving ~90% determinism.

Rule changes MUST bump RULES_VERSION so PipelineRun records stay auditable.
"""

from __future__ import annotations

RULES_VERSION = "flag_rules_v4"

# --- Closed sets --------------------------------------------------------

VALID_FLAG_TYPES = frozenset({
    # Original 5 types
    "missing_endorsement",
    "unacceptable_exception",
    "unresolved_lien",
    "cross_section_mismatch",
    "requirement_missing_proof",
    # Expanded types for comprehensive title examination
    "name_discrepancy",         # party name mismatches, undisclosed parties, grantor/grantee issues
    "marital_status_issue",     # spousal joinder, community property, marital status gaps
    "incomplete_document",      # blank fields, missing signatures, incomplete disclosures
    "regulatory_compliance",    # FinCEN, foreign ownership, BSA, state-specific compliance
    "chain_of_title_gap",       # missing links in ownership chain, unexplained transfers
    "document_defect",          # lines through documents, defective recordings, voided instruments
    "unreleased_mortgage",      # prior mortgages/DOTs without recorded release or reconveyance
    "mineral_rights",           # severed mineral estate, oil/gas leases
    "trust_issue",              # trust documentation gaps, trustee authority
    "estate_issue",             # probate, inheritance tax, deceased parties
    "vesting_issue",            # vesting entity changes, capacity questions
    "tax_issue",                # unpaid taxes, special assessments
})

VALID_SEVERITIES = ("critical", "high", "medium", "low")

# Flag types that are computed deterministically from extractions.
# LLM-generated flags for these types are replaced by the rules engine.
DETERMINISTIC_FLAG_TYPES = frozenset({
    "chain_of_title_gap",
    "unreleased_mortgage",
    "name_discrepancy",
    "cross_section_mismatch",
})

# Severity ordering for comparisons (lower index = higher severity)
_SEVERITY_ORDER = {s: i for i, s in enumerate(VALID_SEVERITIES)}

# --- Floor / cap rules ---------------------------------------------------
# flag_type → minimum severity (floor) — the LLM may not underrate these.
SEVERITY_FLOOR: dict[str, str] = {
    "unresolved_lien": "high",
    "unreleased_mortgage": "high",
    "chain_of_title_gap": "high",
    "name_discrepancy": "medium",
    "missing_endorsement": "medium",
    "marital_status_issue": "medium",
    "trust_issue": "high",
    "estate_issue": "high",
    "tax_issue": "medium",
}

# flag_type → maximum severity (cap) — the LLM may not overrate these.
SEVERITY_CAP: dict[str, str] = {
    "cross_section_mismatch": "medium",
    "incomplete_document": "medium",
    "mineral_rights": "high",
}


def _severity_ge(a: str, b: str) -> bool:
    """Return True if severity *a* is >= severity *b* (higher or equal)."""
    return _SEVERITY_ORDER.get(a, 99) <= _SEVERITY_ORDER.get(b, 99)


def _higher_severity(a: str, b: str) -> str:
    """Return the higher of two severities."""
    return a if _SEVERITY_ORDER.get(a, 99) <= _SEVERITY_ORDER.get(b, 99) else b


def _clamp_severity(flag_type: str, severity: str) -> str:
    """Apply floor and cap rules to a severity value."""
    result = severity

    # Apply floor — raise severity if below minimum
    floor = SEVERITY_FLOOR.get(flag_type)
    if floor and not _severity_ge(result, floor):
        result = floor

    # Apply cap — lower severity if above maximum
    cap = SEVERITY_CAP.get(flag_type)
    if cap and _severity_ge(result, cap) and result != cap:
        # Only cap if result is strictly higher than cap
        if _SEVERITY_ORDER.get(result, 99) < _SEVERITY_ORDER.get(cap, 99):
            result = cap

    return result


def _page_numbers(flag: dict) -> set[int]:
    """Extract unique page numbers from a flag's evidence_refs."""
    refs = flag.get("evidence_refs") or []
    return {ref["page_number"] for ref in refs if "page_number" in ref}


def normalize_flags(flags: list[dict]) -> list[dict]:
    """Deterministic post-processing of LLM-generated flags.

    Steps:
    1. Drop flags with invalid flag_type or empty evidence_refs
    2. Clamp severity to allowed set, apply floor/cap rules
    3. Deduplicate: same flag_type + overlapping pages → merge, keep highest severity
    4. Sort deterministically by (flag_type, first page_number)

    Args:
        flags: list of flag dicts, each with at least flag_type, severity,
               title, description, ai_explanation, evidence_refs.

    Returns:
        New list of normalized flag dicts (original list is not mutated).
    """
    valid: list[dict] = []

    # Step 1+2: validate and clamp
    for f in flags:
        flag_type = f.get("flag_type", "")
        severity = f.get("severity", "")
        evidence_refs = f.get("evidence_refs") or []

        # Drop invalid flag_type
        if flag_type not in VALID_FLAG_TYPES:
            continue

        # Drop flags with no evidence
        if not evidence_refs:
            continue

        # Clamp severity
        if severity not in _SEVERITY_ORDER:
            severity = "medium"  # default unknown severities to medium
        severity = _clamp_severity(flag_type, severity)

        valid.append({**f, "severity": severity})

    # Step 3: deduplicate — same flag_type + overlapping pages → merge
    merged: list[dict] = []
    for flag in valid:
        pages = _page_numbers(flag)
        found_merge = False
        for existing in merged:
            if existing["flag_type"] == flag["flag_type"]:
                existing_pages = _page_numbers(existing)
                if pages & existing_pages:  # overlapping pages
                    # Merge: keep highest severity, combine evidence_refs
                    existing["severity"] = _higher_severity(
                        existing["severity"], flag["severity"]
                    )
                    # Append new evidence refs (deduplicate by page+snippet)
                    seen = {
                        (r.get("page_number"), r.get("text_snippet"))
                        for r in existing["evidence_refs"]
                    }
                    for ref in flag.get("evidence_refs", []):
                        key = (ref.get("page_number"), ref.get("text_snippet"))
                        if key not in seen:
                            existing["evidence_refs"].append(ref)
                            seen.add(key)
                    found_merge = True
                    break
        if not found_merge:
            merged.append({**flag})

    # Step 4: deterministic sort by (flag_type, first page number)
    def _sort_key(f: dict) -> tuple[str, int]:
        pages = _page_numbers(f)
        return (f["flag_type"], min(pages) if pages else 0)

    merged.sort(key=_sort_key)

    return merged


# --- Deterministic flag generators ----------------------------------------


def detect_chain_gaps(chain_result) -> list[dict]:
    """Generate chain_of_title_gap flags from ChainResult.gaps.

    Severity is based on match score:
    - score < 30: critical (completely different names)
    - score < 60: high (low similarity)
    - else: high (similar but not matching — floor enforces high minimum)
    """
    flags: list[dict] = []
    for gap in chain_result.gaps:
        if gap.match_score < 30:
            severity = "critical"
        else:
            severity = "high"

        flags.append({
            "flag_type": "chain_of_title_gap",
            "severity": severity,
            "title": f"Chain gap at position {gap.position}",
            "description": (
                f"Grantee '{gap.expected_grantor}' does not match next grantor "
                f"'{gap.actual_grantor}' (similarity: {gap.match_score:.0f}%)"
            ),
            "ai_explanation": (
                f"The chain of title has a gap after position {gap.position}. "
                f"The previous deed transferred to '{gap.expected_grantor}' but the "
                f"next deed shows '{gap.actual_grantor}' as grantor. "
                f"Name match score: {gap.match_score:.0f}%."
            ),
            "evidence_refs": gap.evidence_refs,
            "source": "deterministic",
        })
    return flags


def detect_unreleased_mortgages_from_chain(chain_result) -> list[dict]:
    """Generate unreleased_mortgage flags from ChainResult.unreleased_mortgages."""
    flags: list[dict] = []
    for um in chain_result.unreleased_mortgages:
        ref_desc = f" (ref: {um.recording_ref})" if um.recording_ref else ""
        flags.append({
            "flag_type": "unreleased_mortgage",
            "severity": "high",
            "title": f"Unreleased mortgage{ref_desc}",
            "description": (
                f"Mortgage from {um.mortgage_link.grantor} to {um.mortgage_link.grantee}"
                f"{ref_desc} has no matching release or reconveyance on record."
            ),
            "ai_explanation": (
                f"A {um.mortgage_link.instrument_type or 'mortgage'} was recorded "
                f"but no corresponding release, satisfaction, or reconveyance was found "
                f"in the examined documents."
            ),
            "evidence_refs": um.evidence_refs,
            "source": "deterministic",
        })
    return flags


def detect_name_discrepancies(extractions: list[dict]) -> list[dict]:
    """Generate name_discrepancy flags from party name comparison."""
    from app.micro_apps.title_intelligence.services.party_normalizer import find_name_discrepancies

    discrepancies = find_name_discrepancies(extractions, threshold=85.0)
    flags: list[dict] = []
    for d in discrepancies:
        flags.append({
            "flag_type": "name_discrepancy",
            "severity": "medium",
            "title": f"Name discrepancy: '{d['name_a']}' vs '{d['name_b']}'",
            "description": (
                f"Party name '{d['name_a']}' ({d['role_a']}) differs from "
                f"'{d['name_b']}' ({d['role_b']}) with {d['score']:.0f}% similarity. "
                f"Match method: {d['match_method']}."
            ),
            "ai_explanation": (
                f"These names appear to refer to the same party but are not identical. "
                f"This could indicate a spelling error, name change, or different legal entity. "
                f"Verify the correct legal name for closing documents."
            ),
            "evidence_refs": d["evidence_refs"],
            "source": "deterministic",
        })
    return flags


def detect_cross_section_mismatches(
    extractions: list[dict],
    sections: list[dict] | None = None,
) -> list[dict]:
    """Generate cross_section_mismatch flags by comparing data across sections.

    Compares property addresses, legal descriptions, and party names across
    different document sections to detect inconsistencies.
    """
    from app.micro_apps.title_intelligence.services.party_normalizer import match_parties

    if not sections or len(sections) < 2:
        return []

    # Build section-to-extraction mapping
    section_extractions: dict[str, list[dict]] = {}
    for ext in extractions:
        # Determine which section this extraction belongs to
        evidence = ext.get("evidence_refs") or []
        if not evidence:
            continue
        page_nums = {r.get("page_number") for r in evidence if "page_number" in r}
        if not page_nums:
            continue

        for sec in sections:
            s_start = sec.get("start_page", 0)
            s_end = sec.get("end_page", 0)
            s_type = sec.get("section_type", "")
            if any(s_start <= pn <= s_end for pn in page_nums):
                section_extractions.setdefault(s_type, []).append(ext)
                break

    if len(section_extractions) < 2:
        return []

    flags: list[dict] = []

    # Compare property descriptions across sections
    property_by_section: dict[str, list[str]] = {}
    for sec_type, exts in section_extractions.items():
        for ext in exts:
            if ext.get("extraction_type") == "property":
                value = ext.get("value") or {}
                addr = value.get("address", "") or value.get("property_address", "")
                if addr:
                    property_by_section.setdefault(sec_type, []).append(addr)

    # Cross-compare property addresses
    sec_types = sorted(property_by_section.keys())
    for i in range(len(sec_types)):
        for j in range(i + 1, len(sec_types)):
            addrs_a = property_by_section[sec_types[i]]
            addrs_b = property_by_section[sec_types[j]]
            for addr_a in addrs_a:
                for addr_b in addrs_b:
                    result = match_parties(addr_a, addr_b, threshold=70.0)
                    if result.is_match and result.score < 100.0:
                        flags.append({
                            "flag_type": "cross_section_mismatch",
                            "severity": "medium",
                            "title": f"Property mismatch: {sec_types[i]} vs {sec_types[j]}",
                            "description": (
                                f"Property address in {sec_types[i]} ('{addr_a}') differs from "
                                f"{sec_types[j]} ('{addr_b}') — {result.score:.0f}% match."
                            ),
                            "ai_explanation": (
                                f"The property description differs between document sections. "
                                f"This may indicate a clerical error or different property references."
                            ),
                            "evidence_refs": [],
                            "source": "deterministic",
                        })

    # Compare party names across sections
    parties_by_section: dict[str, list[tuple[str, list[dict]]]] = {}
    for sec_type, exts in section_extractions.items():
        for ext in exts:
            if ext.get("extraction_type") == "party":
                value = ext.get("value") or {}
                name = value.get("name", "")
                if name:
                    parties_by_section.setdefault(sec_type, []).append(
                        (name, ext.get("evidence_refs") or [])
                    )

    sec_types = sorted(parties_by_section.keys())
    seen_pairs: set[tuple[str, str]] = set()
    for i in range(len(sec_types)):
        for j in range(i + 1, len(sec_types)):
            for name_a, refs_a in parties_by_section[sec_types[i]]:
                for name_b, refs_b in parties_by_section[sec_types[j]]:
                    pair_key = tuple(sorted([name_a.lower(), name_b.lower()]))
                    if pair_key in seen_pairs:
                        continue
                    seen_pairs.add(pair_key)

                    result = match_parties(name_a, name_b, threshold=70.0)
                    if result.is_match and result.score < 100.0:
                        combined_refs = list(refs_a) + list(refs_b)
                        flags.append({
                            "flag_type": "cross_section_mismatch",
                            "severity": "medium",
                            "title": f"Party name mismatch across sections",
                            "description": (
                                f"'{name_a}' in {sec_types[i]} differs from "
                                f"'{name_b}' in {sec_types[j]} — {result.score:.0f}% match."
                            ),
                            "ai_explanation": (
                                f"The same party appears with different names across sections. "
                                f"Verify the correct legal name."
                            ),
                            "evidence_refs": combined_refs,
                            "source": "deterministic",
                        })

    return flags


def generate_deterministic_flags(
    extractions: list[dict],
    sections: list[dict] | None = None,
) -> list[dict]:
    """Generate all deterministic flags from structured extractions.

    Orchestrates chain building, gap detection, unreleased mortgage detection,
    name discrepancy detection, and cross-section mismatch detection.

    Args:
        extractions: List of extraction dicts from the examiner
        sections: List of section dicts (optional, for cross-section checks)

    Returns:
        List of normalized deterministic flag dicts
    """
    from app.micro_apps.title_intelligence.services.chain_builder import build_chain

    all_flags: list[dict] = []

    # Build chain and detect gaps/unreleased mortgages
    chain_result = build_chain(extractions)
    all_flags.extend(detect_chain_gaps(chain_result))
    all_flags.extend(detect_unreleased_mortgages_from_chain(chain_result))

    # Detect name discrepancies
    all_flags.extend(detect_name_discrepancies(extractions))

    # Detect cross-section mismatches
    all_flags.extend(detect_cross_section_mismatches(extractions, sections))

    # Normalize all deterministic flags through the same pipeline
    return normalize_flags(all_flags)


def merge_llm_and_deterministic_flags(
    llm_flags: list[dict],
    deterministic_flags: list[dict],
) -> list[dict]:
    """Merge LLM-generated and deterministic flags.

    Drops ALL LLM flags for DETERMINISTIC_FLAG_TYPES and replaces them
    with rules engine output. LLM flags for non-deterministic types are
    kept as-is.

    Args:
        llm_flags: Normalized LLM-generated flags
        deterministic_flags: Normalized deterministic flags

    Returns:
        Merged and normalized flag list
    """
    # Keep LLM flags only for non-deterministic types
    kept_llm = [
        f for f in llm_flags
        if f.get("flag_type") not in DETERMINISTIC_FLAG_TYPES
    ]

    # Combine and re-normalize (handles dedup across sources)
    combined = kept_llm + deterministic_flags
    return normalize_flags(combined)
