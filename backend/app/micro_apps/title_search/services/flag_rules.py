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

RULES_VERSION = "ta_flag_rules_v2"

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
    # v2: research-driven flags
    "flood_zone_risk",
    "noc_open",
    "permit_violation",
    "tax_delinquent",
    "hoa_violation",
    "lis_pendens",
    "missing_survey",
})

VALID_SEVERITIES = ("critical", "high", "medium", "low")

_SEVERITY_ORDER = {s: i for i, s in enumerate(VALID_SEVERITIES)}

# --- Severity floor/cap rules ---------------------------------------------
# flag_type → minimum severity — rules engine may not underrate these.
SEVERITY_FLOOR: dict[str, str] = {
    "chain_gap": "high",
    "unreleased_mortgage": "high",
    "unsatisfied_lien": "high",
    "lis_pendens": "critical",
    "tax_delinquent": "high",
    "flood_zone_risk": "medium",
}

# flag_type → maximum severity — rules engine may not overrate these.
SEVERITY_CAP: dict[str, str] = {
    "low_confidence": "medium",
    "missing_source": "medium",
    "hoa_violation": "medium",
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


def detect_flood_zone_risk(property_summary: dict[str, Any] | None) -> list[dict]:
    """Detect properties in FEMA high-risk flood zones (AE, VE, A, V)."""
    if not property_summary:
        return []
    lot_land = property_summary.get("lot_and_land", {})
    if not lot_land:
        return []
    flood_zone = lot_land.get("flood_zone", "")
    if not flood_zone:
        return []

    high_risk_zones = {"AE", "VE", "A", "V", "A1", "A99", "AH", "AO", "AR", "V1"}
    zone_upper = flood_zone.strip().upper()
    if zone_upper in high_risk_zones:
        severity = _clamp_severity("flood_zone_risk", "high" if zone_upper in ("AE", "VE", "V", "V1") else "medium")
        return [{
            "flag_type": "flood_zone_risk",
            "severity": severity,
            "title": "Flood Zone Risk",
            "description": f"Property is in FEMA high-risk flood zone {flood_zone}. Flood insurance may be required.",
            "evidence_refs": [{
                "field_name": "flood_zone",
                "text_snippet": f"FEMA flood zone designation: {flood_zone}",
            }],
        }]
    return []


def detect_noc_open(property_summary: dict[str, Any] | None) -> list[dict]:
    """Detect open Notice of Commencement without final payment affidavit."""
    if not property_summary:
        return []
    noc = property_summary.get("notice_of_commencement", {})
    if not noc:
        return []
    if not noc.get("has_noc"):
        return []
    if noc.get("final_payment_affidavit"):
        return []  # Has final payment — no issue

    severity = _clamp_severity("noc_open", "high")
    return [{
        "flag_type": "noc_open",
        "severity": severity,
        "title": "Open Notice of Commencement",
        "description": (
            f"NOC recorded {noc.get('recording_date', 'unknown date')} "
            f"({noc.get('recording_ref', 'no ref')}) without final payment affidavit. "
            "Potential mechanic's lien exposure."
        ),
        "evidence_refs": [{
            "field_name": "notice_of_commencement",
            "text_snippet": f"NOC recorded: {noc.get('recording_ref', 'N/A')}",
        }],
    }]


def detect_permit_violations(property_summary: dict[str, Any] | None) -> list[dict]:
    """Detect open code violations or permit issues."""
    if not property_summary:
        return []
    permits = property_summary.get("permits", [])
    if not permits:
        return []

    flags = []
    for permit in permits:
        status = (permit.get("status") or "").lower()
        if status in ("violation", "open_violation", "code_violation"):
            severity = _clamp_severity("permit_violation", "high")
            flags.append({
                "flag_type": "permit_violation",
                "severity": severity,
                "title": "Permit / Code Violation",
                "description": (
                    f"{permit.get('permit_type', 'Permit')} #{permit.get('permit_number', 'N/A')}: "
                    f"{permit.get('violation_details') or permit.get('description', 'Open violation')}"
                ),
                "evidence_refs": [{
                    "field_name": "permits",
                    "text_snippet": f"Permit {permit.get('permit_number', 'N/A')} — {status}",
                }],
            })
    return flags


def detect_tax_delinquent(property_summary: dict[str, Any] | None) -> list[dict]:
    """Detect delinquent property taxes."""
    if not property_summary:
        return []
    tax = property_summary.get("tax_status", {})
    if not tax:
        return []

    # Handle both formats: string (from PropertyData) and dict (from research data)
    if isinstance(tax, str):
        status = tax.lower()
        tax = {"tax_status": tax}
    else:
        status = (tax.get("tax_status") or "").lower()
    if status in ("delinquent", "unpaid", "past_due"):
        severity = _clamp_severity("tax_delinquent", "high")
        delinquent_amt = tax.get("delinquent_amount")
        amt_str = f" (${delinquent_amt:,.2f})" if delinquent_amt else ""
        return [{
            "flag_type": "tax_delinquent",
            "severity": severity,
            "title": "Delinquent Property Taxes",
            "description": f"Property taxes are {status}{amt_str}. Tax year: {tax.get('tax_year', 'N/A')}.",
            "evidence_refs": [{
                "field_name": "tax_status",
                "text_snippet": f"Tax status: {status}, Year: {tax.get('tax_year', 'N/A')}",
            }],
        }]
    return []


def detect_hoa_violations(property_summary: dict[str, Any] | None) -> list[dict]:
    """Detect open HOA violations."""
    if not property_summary:
        return []
    hoa = property_summary.get("hoa", {})
    if not hoa:
        return []

    violations = hoa.get("hoa_violations", [])
    if not violations:
        return []

    flags = []
    for violation in violations:
        severity = _clamp_severity("hoa_violation", "medium")
        flags.append({
            "flag_type": "hoa_violation",
            "severity": severity,
            "title": "HOA Violation",
            "description": f"HOA violation: {violation}",
            "evidence_refs": [{
                "field_name": "hoa_violations",
                "text_snippet": violation,
            }],
        })
    return flags


def detect_lis_pendens(property_summary: dict[str, Any] | None) -> list[dict]:
    """Detect active lis pendens or foreclosure proceedings."""
    if not property_summary:
        return []
    proceedings = property_summary.get("court_proceedings", [])
    if not proceedings:
        return []

    flags = []
    for case in proceedings:
        case_type = (case.get("case_type") or "").lower()
        status = (case.get("status") or "").lower()
        if case_type in ("foreclosure", "lis_pendens", "lis pendens") and status not in ("dismissed", "closed", "resolved"):
            severity = _clamp_severity("lis_pendens", "critical")
            flags.append({
                "flag_type": "lis_pendens",
                "severity": severity,
                "title": "Active Lis Pendens / Foreclosure",
                "description": (
                    f"{case.get('case_type', 'Lis Pendens')}: Case #{case.get('case_number', 'N/A')} "
                    f"filed {case.get('filing_date', 'N/A')}. Status: {case.get('status', 'N/A')}. "
                    f"Parties: {case.get('parties', 'N/A')}"
                ),
                "evidence_refs": [{
                    "field_name": "court_proceedings",
                    "text_snippet": f"Case #{case.get('case_number', 'N/A')} — {case.get('case_type', 'N/A')}",
                }],
            })
    return flags


def detect_unreleased_mortgages_research(
    property_summary: dict[str, Any] | None,
) -> list[dict]:
    """Detect unreleased mortgages from research data (property_summary.mortgages).

    In grounded/research mode, mortgage data lives in property_summary as JSON
    rather than as TADocument ORM records. This rule checks the status field
    for keywords indicating no satisfaction has been recorded.
    """
    if not property_summary:
        return []
    mortgages = property_summary.get("mortgages", [])
    if not isinstance(mortgages, list):
        return []

    _unsatisfied_keywords = ("active", "open", "no satisfaction", "unreleased", "outstanding")
    flags = []
    for m in mortgages:
        if not isinstance(m, dict):
            continue
        status = (m.get("status") or "").lower()
        notes = (m.get("notes") or "").lower()
        combined = f"{status} {notes}"
        if any(kw in combined for kw in _unsatisfied_keywords):
            lender = m.get("lender", "Unknown")
            amount = m.get("amount", "Unknown")
            ref = m.get("recording_ref", "N/A")
            severity = _clamp_severity("unreleased_mortgage", "high")
            flags.append({
                "flag_type": "unreleased_mortgage",
                "severity": severity,
                "title": "Unreleased Mortgage",
                "description": (
                    f"Mortgage by {lender} ({amount}) has no recorded satisfaction. "
                    f"Ref: {ref}. Must be released or paid at closing."
                ),
                "evidence_refs": [{
                    "field_name": "mortgages",
                    "text_snippet": f"{lender} — {amount} ({status})",
                }],
            })
    return flags


def detect_missing_survey(property_summary: dict[str, Any] | None) -> list[dict]:
    """Flag recommendation for survey if none exists."""
    if not property_summary:
        return []
    survey = property_summary.get("survey_plat", {})
    if not isinstance(survey, dict):
        return []
    rec = (survey.get("recommendation") or "").lower()
    if any(kw in rec for kw in ("recommended", "strongly recommended", "should obtain")):
        severity = _clamp_severity("missing_survey", "medium")
        return [{
            "flag_type": "missing_survey",
            "severity": severity,
            "title": "Survey Recommended",
            "description": survey.get("recommendation", "A current boundary survey is recommended prior to closing."),
            "evidence_refs": [{"field_name": "survey_plat", "text_snippet": rec[:100]}],
        }]
    return []


def detect_all_flags(
    documents: list[Any],
    property_summary: dict[str, Any] | None = None,
) -> list[dict]:
    """Run all deterministic flag detection rules.

    Args:
        documents: TADocument ORM objects or dicts (for v1 document-based rules).
        property_summary: Research data dict with 22 entities (for v2 research-based rules).

    Returns a deduplicated, severity-clamped, deterministically-sorted list of
    flag dicts.
    """
    flags: list[dict] = []
    # v1 document-based rules
    flags.extend(detect_unreleased_mortgages(documents))
    flags.extend(detect_low_confidence(documents))
    # v2 research-based rules
    if property_summary:
        flags.extend(detect_flood_zone_risk(property_summary))
        flags.extend(detect_noc_open(property_summary))
        flags.extend(detect_permit_violations(property_summary))
        flags.extend(detect_tax_delinquent(property_summary))
        flags.extend(detect_hoa_violations(property_summary))
        flags.extend(detect_lis_pendens(property_summary))
        flags.extend(detect_unreleased_mortgages_research(property_summary))
        flags.extend(detect_missing_survey(property_summary))
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
