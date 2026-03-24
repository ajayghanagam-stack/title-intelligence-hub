"""Deterministic post-processing rules for AI-generated risk flags.

Normalizes, validates, and deduplicates LLM-generated flags so that the same
document inputs produce identical flag output regardless of LLM temperature
variation.  Inserted into the pipeline after the RiskAgent LLM call and before
the DB commit.

Rule changes MUST bump RULES_VERSION so PipelineRun records stay auditable.
"""

from __future__ import annotations

RULES_VERSION = "flag_rules_v1"

# --- Closed sets --------------------------------------------------------

VALID_FLAG_TYPES = frozenset({
    "missing_endorsement",
    "unacceptable_exception",
    "unresolved_lien",
    "cross_section_mismatch",
    "requirement_missing_proof",
})

VALID_SEVERITIES = ("critical", "high", "medium", "low")

# Severity ordering for comparisons (lower index = higher severity)
_SEVERITY_ORDER = {s: i for i, s in enumerate(VALID_SEVERITIES)}

# --- Floor / cap rules ---------------------------------------------------
# flag_type → minimum severity (floor) — the LLM may not underrate these.
SEVERITY_FLOOR: dict[str, str] = {
    "unresolved_lien": "high",
    "missing_endorsement": "medium",
}

# flag_type → maximum severity (cap) — the LLM may not overrate these.
SEVERITY_CAP: dict[str, str] = {
    "cross_section_mismatch": "medium",
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
