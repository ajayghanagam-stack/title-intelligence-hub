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


def _find_extraction_from_list(extractions: list, ext_type: str, *label_patterns: str) -> str:
    """Find a matching extraction value from a list of Extraction model instances."""
    for pat in label_patterns:
        lower_pat = pat.lower()
        for ext in extractions:
            if ext.extraction_type == ext_type and lower_pat in ext.label.lower():
                val = _extract_value(ext.value)
                if val:
                    return val
    return ""


async def generate_report_pdf(
    db: AsyncSession,
    org_id: uuid.UUID,
    pack_id: uuid.UUID,
    storage: StorageProvider,
) -> bytes:
    """Generate a data-driven Title Intelligence Report PDF.

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

    # Extract property info from extractions (try policy_info first, then property)
    property_address = (
        _find_extraction(extractions, "policy_info", "address", "property address", "full_address")
        or _find_extraction(extractions, "property", "address", "property address", "full_address", "insured property")
    )
    order_number = (
        _find_extraction(extractions, "policy_info", "commitment number", "order number", "order no", "commitment_number")
        or _find_extraction(extractions, "property", "commitment number", "order number", "order no")
    )
    commitment_date = (
        _find_extraction(extractions, "policy_info", "effective date", "commitment date", "effective_date")
        or _find_extraction(extractions, "property", "effective date", "commitment date")
    )
    issued_by = _find_extraction(extractions, "party", "title company", "underwriter", "issuer", "issued by", "issuing agent")

    # Build exception rows from flags
    sorted_flags = sorted(flags, key=lambda f: (_SEVERITY_ORDER.get(f.severity, 9), f.flag_type))
    exceptions = []
    for i, flag in enumerate(sorted_flags, start=1):
        # Build doc ref from evidence_refs
        doc_ref = ""
        if flag.evidence_refs:
            pages = sorted({ref.get("page_number", 0) for ref in flag.evidence_refs if ref.get("page_number")})
            if pages:
                doc_ref = "p. " + ", ".join(str(p) for p in pages)

        # Action based on severity
        action = _action_for_severity(flag.severity)

        exceptions.append({
            "id": i,
            "severity": {"critical": "critical", "high": "warning", "medium": "warning", "low": "review"}.get(flag.severity, flag.severity),
            "category": flag.flag_type.replace("_", " ").title(),
            "description": flag.title,
            "doc_ref": doc_ref,
            "action": action,
        })

    # Compute counts
    critical_count = sum(1 for f in flags if f.severity == "critical")
    warning_count = sum(1 for f in flags if f.severity in ("high", "medium"))
    review_count = sum(1 for f in flags if f.status in ("open", "escalated"))

    generated_at = datetime.now(timezone.utc).strftime("%B %d, %Y at %I:%M %p UTC")

    # Generate PDF
    pdf_bytes = generate_pack_report_pdf(
        property_address=property_address or pack.name,
        order_number=order_number,
        commitment_date=commitment_date,
        issued_by=issued_by,
        generated_at=generated_at,
        critical_count=critical_count,
        warning_count=warning_count,
        review_count=review_count,
        exceptions=exceptions,
    )

    # Cache
    try:
        await storage.put_object(cache_uri, pdf_bytes, content_type="application/pdf")
        logger.info("Cached report at %s", cache_uri)
    except Exception:
        logger.warning("Failed to cache report (non-fatal)", exc_info=True)

    return pdf_bytes


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


def _action_for_severity(severity: str) -> str:
    """Return a recommended action string based on flag severity."""
    actions = {
        "critical": "Must resolve before closing",
        "high": "Resolve before closing",
        "medium": "Review and address",
        "low": "Note for record",
    }
    return actions.get(severity, "Review")


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
