"""Data-driven report generation — no LLM needed.

Includes both PDF report generation and template-based executive summary
generation. The summary generator replaces the LLM-based summary in
stage_complete (Phase 7), saving ~10-15s per pipeline run.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.micro_apps.title_intelligence.models.extraction import Extraction
from app.micro_apps.title_intelligence.models.flag import Flag
from app.micro_apps.title_intelligence.models.pack import Pack
from app.micro_apps.title_intelligence.models.section import Section
from app.micro_apps.title_intelligence.services.storage import StorageProvider
from app.core.exceptions import ForbiddenError, NotFoundError

logger = logging.getLogger(__name__)

# Severity sort order
_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}

# Human-readable flag type labels
_FLAG_TYPE_LABELS = {
    "missing_endorsement": "missing endorsement",
    "unacceptable_exception": "unacceptable exception",
    "unresolved_lien": "unresolved lien",
    "unreleased_mortgage": "unreleased mortgage",
    "cross_section_mismatch": "cross-section mismatch",
    "requirement_missing_proof": "requirement without proof of satisfaction",
    "name_discrepancy": "party name discrepancy",
    "marital_status_issue": "marital status issue",
    "incomplete_document": "incomplete document",
    "regulatory_compliance": "regulatory compliance concern",
    "chain_of_title_gap": "chain of title gap",
    "document_defect": "document defect",
    "mineral_rights": "mineral rights concern",
    "trust_issue": "trust documentation issue",
    "estate_issue": "estate administration issue",
    "vesting_issue": "vesting issue",
    "tax_issue": "tax issue",
}


def generate_data_driven_summary(
    pack_name: str,
    extractions: list,
    flags: list,
) -> str:
    """Generate a bullet-point executive summary from structured data.

    Produces the same format as the LLM-based summary (newline-separated
    bullet points starting with '- ') but deterministically from data.
    Eliminates the 10-15s LLM call from stage_complete.

    Args:
        pack_name: Display name of the title pack
        extractions: List of Extraction model instances
        flags: List of Flag model instances

    Returns:
        Bullet-point summary string (each line starts with '- ')
    """
    bullets: list[str] = []

    # Categorize flags
    open_flags = [f for f in flags if f.status == "open"]
    critical_flags = [f for f in open_flags if f.severity == "critical"]
    high_flags = [f for f in open_flags if f.severity == "high"]
    medium_flags = [f for f in open_flags if f.severity == "medium"]
    low_flags = [f for f in open_flags if f.severity == "low"]

    # Bullet 1: Overall status based on flags
    if not open_flags:
        status_text = "Title commitment has no open issues remaining and is cleared for closing."
    elif critical_flags:
        status_text = (
            f"Title commitment has {len(open_flags)} open issue{'s' if len(open_flags) != 1 else ''}, "
            f"including {len(critical_flags)} critical. "
            f"Critical issues must be resolved before closing."
        )
    elif high_flags:
        status_text = (
            f"Title commitment has {len(open_flags)} open issue{'s' if len(open_flags) != 1 else ''} "
            f"requiring attention before closing."
        )
    else:
        status_text = (
            f"Title commitment has {len(open_flags)} minor open item{'s' if len(open_flags) != 1 else ''} "
            f"to review before closing."
        )
    bullets.append(status_text)

    # Bullet per critical issue (name each specifically)
    for f in critical_flags:
        label = _FLAG_TYPE_LABELS.get(f.flag_type, f.flag_type.replace("_", " "))
        bullets.append(f"CRITICAL: {f.title} — {label} that must be resolved before closing.")

    # Bullet per high issue (name each specifically)
    for f in high_flags:
        label = _FLAG_TYPE_LABELS.get(f.flag_type, f.flag_type.replace("_", " "))
        bullets.append(f"{f.title} — {label} that should be resolved before closing.")

    # Summary bullet for medium/low issues
    if medium_flags or low_flags:
        parts = []
        if medium_flags:
            parts.append(f"{len(medium_flags)} medium-severity")
        if low_flags:
            parts.append(f"{len(low_flags)} low-severity")
        count_text = " and ".join(parts)
        bullets.append(f"Additionally, {count_text} item{'s' if (len(medium_flags) + len(low_flags)) != 1 else ''} should be reviewed.")

    # Final bullet: next steps
    if not open_flags:
        bullets.append("All issues have been resolved. The title commitment is cleared for closing.")
    elif critical_flags:
        bullets.append(
            f"Recommended next steps: resolve {len(critical_flags)} critical "
            f"issue{'s' if len(critical_flags) != 1 else ''} immediately, "
            f"then address remaining items before scheduling closing."
        )
    elif high_flags:
        bullets.append(
            f"Recommended next steps: address {len(high_flags)} high-priority "
            f"issue{'s' if len(high_flags) != 1 else ''} to bring the title to closing readiness."
        )
    else:
        bullets.append(
            "Recommended next steps: review and address remaining items. "
            "The title is approaching closing readiness."
        )

    return "\n".join(f"- {b}" for b in bullets)


async def generate_report_pdf(
    db: AsyncSession,
    org_id: uuid.UUID,
    pack_id: uuid.UUID,
    storage: StorageProvider,
) -> bytes:
    """Generate a professional Title Examination Report PDF.

    Fetches pack data, builds structured inputs, renders PDF via pdf_service,
    caches in storage, and returns PDF bytes.
    """
    from app.micro_apps.title_intelligence.services.pdf_service import generate_pack_report_pdf

    # Check cache
    cache_uri = storage.make_report_path(org_id, pack_id, "report.pdf")
    try:
        if await storage.exists(cache_uri):
            logger.info("Serving cached report: %s", cache_uri)
            return await storage.read(cache_uri)
    except Exception:
        logger.debug("Cache miss or read error for %s, regenerating", cache_uri)

    # Fetch pack
    pack = (await db.execute(
        select(Pack).where(Pack.id == pack_id, Pack.org_id == org_id)
    )).scalar_one()

    # Fetch extractions
    ext_result = await db.execute(
        select(Extraction).where(Extraction.pack_id == pack_id, Extraction.org_id == org_id)
    )
    extractions = list(ext_result.scalars().all())

    # Fetch flags
    flag_result = await db.execute(
        select(Flag).where(Flag.pack_id == pack_id, Flag.org_id == org_id)
    )
    flags = list(flag_result.scalars().all())

    # Fetch sections (for Schedule B split logic)
    sec_result = await db.execute(
        select(Section).where(Section.pack_id == pack_id, Section.org_id == org_id)
    )
    sections = list(sec_result.scalars().all())

    # Assemble full report data dict
    report_data = assemble_report_data(pack, extractions, flags, sections)

    # Generate PDF
    pdf_bytes = generate_pack_report_pdf(report_data)

    # Cache
    try:
        await storage.put_object(cache_uri, pdf_bytes, content_type="application/pdf")
        logger.info("Cached report at %s", cache_uri)
    except Exception:
        logger.warning("Failed to cache report (non-fatal)", exc_info=True)

    return pdf_bytes


# Known standard exception phrases for Schedule B-1 heuristic
_STANDARD_EXCEPTION_PHRASES = [
    "rights of parties in possession",
    "encroachments, overlaps, boundary line disputes",
    "easements or claims of easements",
    "lien for services, labor or material",
    "taxes or assessments",
    "facts, rights, or claims which a correct survey",
    "survey matters",
    "mechanic",
    "materialmen",
    "rights or claims which are not shown by the public records",
    "unpatented mining claims",
    "water rights",
    "reservations or exceptions in patents",
]


def assemble_report_data(
    pack: Pack,
    extractions: list,
    flags: list,
    sections: list,
) -> dict:
    """Build the full report_data dict for the PDF renderer."""
    fe = _find_extraction  # alias for brevity

    # ── Transaction Summary fields ──
    property_address = (
        fe(extractions, "property", "address", "property address", "full_address", "insured property", "subject property")
        or fe(extractions, "policy_info", "address", "property address", "full_address")
        or pack.name
    )
    county = fe(extractions, "property", "county")
    state = fe(extractions, "property", "state")
    legal_description = fe(extractions, "property", "legal description", "legal_description")
    interest_type = fe(extractions, "property", "interest type", "interest_type", "fee simple", "estate type")

    # Commitment / file numbers — Claude labels these as "GF Number" and "FAF File Number"
    commitment_number = (
        fe(extractions, "policy_info", "gf number", "gf_number", "commitment number", "order number",
           "order no", "commitment_number", "file number", "file no")
        or fe(extractions, "property", "commitment number", "order number", "order no")
    )
    faf_file_number = fe(extractions, "policy_info", "faf file number", "faf_file_number", "faf file", "underwriter file")

    effective_date = (
        fe(extractions, "policy_info", "effective date", "commitment date", "effective_date")
        or fe(extractions, "property", "effective date", "commitment date")
    )
    issued_date = fe(extractions, "policy_info", "issued date", "issued_date", "issue date", "date issued")

    # Policies — Claude extracts "Owner's Policy" and "Lender's Policy" as separate policy_info items
    owners_policy = fe(extractions, "policy_info", "owner's policy", "owners policy", "owner policy", "t-1")
    lenders_policy = fe(extractions, "policy_info", "lender's policy", "lenders policy", "lender policy", "t-2")
    # Fallback: generic policy amount
    policy_amount = owners_policy or fe(extractions, "policy_info", "policy amount", "amount", "premium")

    # Parties — Claude uses roles: current_owner, proposed_buyer, issuing_agent
    buyer_borrower = fe(extractions, "party", "proposed buyer", "proposed_buyer", "buyer",
                        "borrower", "proposed insured", "vestee")
    seller = fe(extractions, "party", "current owner", "current_owner", "seller", "grantor")
    lender = fe(extractions, "party", "lender", "mortgagee", "proposed lender")
    title_company = fe(extractions, "party", "issuing agent", "issuing_agent", "title company",
                       "title agent", "closing agent")
    underwriter = fe(extractions, "party", "underwriter", "issuer", "issued by")

    generated_at = datetime.now(timezone.utc).strftime("%B %d, %Y at %I:%M %p UTC")

    # ── Flags by severity ──
    open_flags = [f for f in flags if f.status == "open"]
    sorted_open = sorted(open_flags, key=lambda f: (_SEVERITY_ORDER.get(f.severity, 9), f.flag_type))
    flags_by_severity: dict[str, list[dict]] = {"critical": [], "high": [], "medium": [], "low": []}
    all_flags_list: list[dict] = []
    for f in sorted_open:
        page_ref = _page_ref_from_evidence(f.evidence_refs)
        flag_dict = {
            "flag_type": f.flag_type,
            "severity": f.severity,
            "title": f.title,
            "description": f.description,
            "ai_explanation": f.ai_explanation,
            "evidence_refs": f.evidence_refs or [],
            "status": f.status,
            "note": f.note,
            "page_ref": page_ref,
        }
        flags_by_severity.get(f.severity, flags_by_severity["low"]).append(flag_dict)
        all_flags_list.append(flag_dict)

    total_open = len(open_flags)

    # Risk assessment narrative (reuse generate_data_driven_summary)
    risk_assessment = generate_data_driven_summary(pack.name, extractions, flags)

    # ── Build section ID → section_type map ──
    section_map: dict[str, str] = {}
    for sec in sections:
        section_map[str(sec.id)] = sec.section_type

    # ── Schedule B: split standard vs specific exceptions ──
    standard_exceptions: list[dict] = []
    specific_exceptions: list[dict] = []
    exception_extractions = [e for e in extractions if e.extraction_type == "exception"]

    std_num = 0
    spec_num = 0
    for ext in exception_extractions:
        val = ext.value if isinstance(ext.value, dict) else {}
        desc = val.get("description", "") or _extract_value(ext.value)
        page_ref = _page_ref_from_evidence(ext.evidence_refs)

        is_standard = _is_standard_exception(ext, val, section_map)

        if is_standard:
            std_num += 1
            flag_match = _find_matching_flag(ext, flags)
            standard_exceptions.append({
                "number": val.get("exception_number", std_num),
                "title": ext.label,
                "description": desc or ext.label,
                "severity": flag_match.severity if flag_match else "low",
                "page_ref": page_ref,
                "note": flag_match.note if flag_match else None,
            })
        else:
            spec_num += 1
            flag_match = _find_matching_flag(ext, flags)
            specific_exceptions.append({
                "number": val.get("exception_number", spec_num),
                "title": ext.label,
                "description": desc or ext.label,
                "severity": flag_match.severity if flag_match else "",
                "status": flag_match.status if flag_match else "open",
                "page_ref": page_ref,
                "note": flag_match.note if flag_match else None,
            })

    # If no exception extractions, fall back to building from flags
    if not exception_extractions and flags:
        all_sorted_flags = sorted(flags, key=lambda f: (_SEVERITY_ORDER.get(f.severity, 9), f.flag_type))
        for i, f in enumerate(all_sorted_flags, 1):
            page_ref = _page_ref_from_evidence(f.evidence_refs)
            specific_exceptions.append({
                "number": i,
                "title": f.title,
                "description": f.description or f.title,
                "severity": f.severity,
                "status": f.status,
                "page_ref": page_ref,
                "note": f.note,
            })

    # ── Schedule C: Requirements ──
    requirements: list[dict] = []
    req_extractions = [e for e in extractions if e.extraction_type == "requirement"]
    for i, ext in enumerate(req_extractions, 1):
        val = ext.value if isinstance(ext.value, dict) else {}
        desc = val.get("description", "") or _extract_value(ext.value)
        status = val.get("status", "Open")
        page_ref = _page_ref_from_evidence(ext.evidence_refs)
        # Determine priority from matching flag
        flag_match = _find_matching_flag(ext, flags)
        priority = _determine_priority(flag_match, status)
        requirements.append({
            "number": val.get("requirement_number", i),
            "title": ext.label,
            "description": desc or ext.label,
            "priority": priority,
            "status": status,
            "page_ref": page_ref,
            "note": flag_match.note if flag_match else None,
        })

    # ── Warnings: critical + high + medium flags with explanations ──
    warnings: list[dict] = []
    for sev in ("critical", "high", "medium"):
        for fd in flags_by_severity.get(sev, []):
            warnings.append({
                "title": fd["title"],
                "explanation": fd.get("ai_explanation", "") or fd.get("description", ""),
                "flag_type": fd["flag_type"],
                "severity": fd["severity"],
            })

    # ── Pre-Closing Checklist ──
    checklist_items = _build_checklist(flags, requirements)

    return {
        "subtitle": "Exceptions from Coverage & Schedule C Warnings",
        "property_address": property_address,
        "county": county,
        "state": state,
        "legal_description": legal_description,
        "interest_type": interest_type,
        "commitment_number": commitment_number,
        "faf_file_number": faf_file_number,
        "effective_date": effective_date,
        "issued_date": issued_date,
        "owners_policy": owners_policy,
        "lenders_policy": lenders_policy,
        "policy_amount": policy_amount,
        "buyer_borrower": buyer_borrower,
        "seller": seller,
        "lender": lender,
        "title_company": title_company,
        "underwriter": underwriter,
        "generated_at": generated_at,
        "flags_by_severity": flags_by_severity,
        "total_open": total_open,
        "risk_assessment": risk_assessment,
        "standard_exceptions": standard_exceptions,
        "specific_exceptions": specific_exceptions,
        "requirements": requirements,
        "warnings": warnings,
        "checklist_items": checklist_items,
        "all_flags": all_flags_list,
    }


def _determine_priority(flag_match, status: str) -> str:
    """Determine priority label for a requirement based on matching flag."""
    if flag_match:
        if flag_match.severity in ("critical", "high"):
            return "MUST CLEAR"
        if flag_match.severity == "medium":
            return "REQUIRED"
    if status and "info" in status.lower():
        return "INFORMATIONAL"
    return "REQUIRED"


def _is_standard_exception(ext, val: dict, section_map: dict[str, str]) -> bool:
    """Determine if an exception extraction is a standard (B1) exception."""
    # Check by section_id → section_type
    if ext.section_id:
        sec_type = section_map.get(str(ext.section_id), "")
        if sec_type == "schedule_b1":
            return True
        if sec_type == "schedule_b2":
            return False

    # Check by value field
    if val.get("standard") is True:
        return True
    if val.get("standard") is False:
        return False

    # Heuristic: match against known standard exception phrases
    desc = (val.get("description", "") or ext.label).lower()
    for phrase in _STANDARD_EXCEPTION_PHRASES:
        if phrase in desc:
            return True

    return False


def _find_matching_flag(ext, flags: list):
    """Find a flag that matches an exception extraction by description overlap."""
    desc = (_extract_value(ext.value) or ext.label).lower()
    if not desc:
        return None
    for f in flags:
        if f.title.lower() in desc or desc in f.title.lower():
            return f
        if f.description and (f.description.lower() in desc or desc in f.description.lower()):
            return f
    return None


def _page_ref_from_evidence(evidence_refs: list[dict] | None) -> str:
    """Build a page reference string from evidence_refs."""
    if not evidence_refs:
        return ""
    pages = sorted({r.get("page_number", 0) for r in evidence_refs if r.get("page_number")})
    if pages:
        return "p. " + ", ".join(str(p) for p in pages)
    return ""


_SEVERITY_DISPLAY = {
    "critical": "CRITICAL",
    "high": "HIGH",
    "medium": "MODERATE",
    "low": "STANDARD",
}


def _build_checklist(flags: list, requirements: list[dict]) -> list[dict]:
    """Build pre-closing checklist: one item per open flag, sorted by severity."""
    open_flags = [f for f in flags if f.status == "open"]
    sorted_flags = sorted(open_flags, key=lambda f: (_SEVERITY_ORDER.get(f.severity, 9), f.flag_type))

    items: list[dict] = []
    for i, f in enumerate(sorted_flags, 1):
        items.append({
            "number": i,
            "action": f.title,
            "priority": _SEVERITY_DISPLAY.get(f.severity, f.severity.upper()),
            "checked": False,
            "note": f.note,
        })

    return items


def _find_extraction(extractions: list, ext_type: str, *label_patterns: str) -> str:
    """Find a matching extraction value by type and label patterns."""
    for pat in label_patterns:
        lower_pat = pat.lower()
        for ext in extractions:
            if ext.extraction_type == ext_type and lower_pat in ext.label.lower():
                val = _extract_value(ext.value)
                if val:
                    return val
    return ""


def _extract_value(v: object) -> str:
    """Extract a string value from an extraction's value field."""
    if isinstance(v, str):
        return v
    if isinstance(v, dict):
        for key in ("value", "field_value", "address", "full_address", "name", "amount", "number", "date", "text"):
            if isinstance(v.get(key), str):
                return v[key]
        for val in v.values():
            if isinstance(val, str) and val:
                return val
    return ""


async def get_report_by_uri_or_raise(
    org_id: uuid.UUID,
    pack_id: uuid.UUID,
    uri: str,
    storage: StorageProvider,
) -> bytes:
    """Read a previously stored report by URI, validating tenant ownership."""
    expected_prefix = f"{org_id}/{pack_id}/reports/"
    if not uri.startswith(expected_prefix):
        raise ForbiddenError("Report URI does not belong to this pack")
    try:
        return await storage.read(uri)
    except Exception:
        raise NotFoundError("Report")
