"""Deterministic flag detection rules for Title Search & Abstracting.

Centralizes all flag creation logic so that the same documents and chain links
always produce identical flags. Rule changes MUST bump RULES_VERSION so
TAPipelineRun records stay auditable and cache keys auto-invalidate.

This module is the single source of truth for:
- Which conditions produce flags
- What severity each flag type receives
- How flags are deduplicated and normalized
"""

from __future__ import annotations

from typing import Any

RULES_VERSION = "ta_flag_rules_v1"

# --- Closed sets -----------------------------------------------------------

VALID_FLAG_TYPES = frozenset({
    "chain_gap",
    "name_mismatch",
    "unreleased_mortgage",
    "unsatisfied_lien",
    "judgment_match",
    "easement_conflict",
    "missing_source",
    "low_confidence",
})

VALID_SEVERITIES = ("critical", "high", "medium", "low")

_SEVERITY_ORDER = {s: i for i, s in enumerate(VALID_SEVERITIES)}

# --- Severity floor/cap rules ---------------------------------------------
# flag_type → minimum severity — rules engine may not underrate these.
SEVERITY_FLOOR: dict[str, str] = {
    "chain_gap": "high",
    "unreleased_mortgage": "high",
    "unsatisfied_lien": "high",
}

# flag_type → maximum severity — rules engine may not overrate these.
SEVERITY_CAP: dict[str, str] = {
    "low_confidence": "medium",
    "missing_source": "medium",
}

# --- Confidence threshold --------------------------------------------------
LOW_CONFIDENCE_THRESHOLD = 0.70


def _severity_ge(a: str, b: str) -> bool:
    """Return True if severity *a* is >= severity *b* (higher or equal)."""
    return _SEVERITY_ORDER.get(a, 99) <= _SEVERITY_ORDER.get(b, 99)


def _clamp_severity(flag_type: str, severity: str) -> str:
    """Apply floor and cap rules to a severity value."""
    if severity not in _SEVERITY_ORDER:
        severity = "medium"

    # Apply floor
    floor = SEVERITY_FLOOR.get(flag_type)
    if floor and not _severity_ge(severity, floor):
        severity = floor

    # Apply cap
    cap = SEVERITY_CAP.get(flag_type)
    if cap and _SEVERITY_ORDER.get(severity, 99) < _SEVERITY_ORDER.get(cap, 99):
        severity = cap

    return severity


def detect_unreleased_mortgages(documents: list[Any]) -> list[dict]:
    """Detect mortgages without corresponding satisfactions.

    Args:
        documents: list of TADocument ORM objects (or dicts with same keys)
    Returns:
        list of flag dicts ready for DB insertion
    """
    mortgage_docs = [d for d in documents if _attr(d, "doc_type") == "mortgage"]
    satisfaction_docs = [d for d in documents if _attr(d, "doc_type") == "satisfaction"]
    satisfaction_refs = {_attr(d, "recording_ref") for d in satisfaction_docs if _attr(d, "recording_ref")}

    flags = []
    for mortgage in mortgage_docs:
        ref = _attr(mortgage, "recording_ref")
        if ref not in satisfaction_refs:
            severity = _clamp_severity("unreleased_mortgage", "high")
            flags.append({
                "flag_type": "unreleased_mortgage",
                "severity": severity,
                "title": "Unreleased Mortgage",
                "description": f"Mortgage {ref or 'unknown'} has no corresponding satisfaction.",
                "document_id": _attr(mortgage, "id"),
                "evidence_refs": [
                    {
                        "document_ref": ref,
                        "field_name": "recording_ref",
                        "text_snippet": f"Mortgage recorded as {ref or 'unknown'}",
                        "confidence": _attr(mortgage, "confidence"),
                    },
                ],
            })
    return flags


def detect_low_confidence(documents: list[Any]) -> list[dict]:
    """Detect documents with confidence below threshold.

    Args:
        documents: list of TADocument ORM objects (or dicts with same keys)
    Returns:
        list of flag dicts ready for DB insertion
    """
    flags = []
    for doc in documents:
        confidence = _attr(doc, "confidence")
        if confidence is not None and confidence < LOW_CONFIDENCE_THRESHOLD:
            ref = _attr(doc, "recording_ref")
            severity = _clamp_severity("low_confidence", "medium")
            flags.append({
                "flag_type": "low_confidence",
                "severity": severity,
                "title": "Low Confidence Parse",
                "description": f"Document {ref or 'unknown'} parsed with confidence {confidence:.2f}",
                "document_id": _attr(doc, "id"),
                "evidence_refs": [
                    {
                        "document_ref": ref,
                        "field_name": "confidence",
                        "text_snippet": f"Parsed with confidence {confidence:.2f} (threshold {LOW_CONFIDENCE_THRESHOLD})",
                        "confidence": confidence,
                    },
                ],
            })
    return flags


def detect_all_flags(documents: list[Any]) -> list[dict]:
    """Run all deterministic flag detection rules against documents.

    Returns a deduplicated, severity-clamped, deterministically-sorted list of
    flag dicts.
    """
    flags: list[dict] = []
    flags.extend(detect_unreleased_mortgages(documents))
    flags.extend(detect_low_confidence(documents))
    return normalize_flags(flags)


def normalize_flags(flags: list[dict]) -> list[dict]:
    """Normalize, deduplicate, and sort flags deterministically.

    Steps:
    1. Validate flag_type against closed set
    2. Clamp severity with floor/cap rules
    3. Deduplicate: same flag_type + same document_id → merge, keep highest severity
    4. Sort by (severity_order, flag_type, description)
    """
    valid: list[dict] = []
    for f in flags:
        flag_type = f.get("flag_type", "")
        if flag_type not in VALID_FLAG_TYPES:
            continue
        severity = _clamp_severity(flag_type, f.get("severity", "medium"))
        valid.append({**f, "severity": severity})

    # Deduplicate by (flag_type, document_id)
    seen: dict[tuple[str, str | None], dict] = {}
    for f in valid:
        key = (f["flag_type"], str(f.get("document_id")) if f.get("document_id") else None)
        if key in seen:
            existing = seen[key]
            # Keep higher severity
            if _SEVERITY_ORDER.get(f["severity"], 99) < _SEVERITY_ORDER.get(existing["severity"], 99):
                existing["severity"] = f["severity"]
        else:
            seen[key] = {**f}

    result = list(seen.values())

    # Deterministic sort: severity (critical first), then flag_type, then description
    result.sort(key=lambda f: (
        _SEVERITY_ORDER.get(f["severity"], 99),
        f["flag_type"],
        f.get("description", ""),
    ))
    return result


def _attr(obj: Any, key: str) -> Any:
    """Get attribute from ORM object or dict."""
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)
