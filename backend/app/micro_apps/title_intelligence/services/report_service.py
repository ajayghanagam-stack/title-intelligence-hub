"""Data-driven report generation — no LLM needed."""

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.micro_apps.title_intelligence.models.extraction import Extraction
from app.micro_apps.title_intelligence.models.flag import Flag
from app.micro_apps.title_intelligence.models.pack import Pack
from app.micro_apps.title_intelligence.services.readiness_service import calculate_readiness
from app.micro_apps.title_intelligence.services.storage import StorageProvider
from app.core.exceptions import ForbiddenError, NotFoundError

logger = logging.getLogger(__name__)

# Severity sort order
_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


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

    # Calculate readiness
    readiness = await calculate_readiness(db, org_id, pack_id)

    # Extract property info from extractions
    property_address = _find_extraction(extractions, "property_info", "address", "property address", "full_address")
    order_number = _find_extraction(extractions, "property_info", "commitment number", "order number", "order no", "commitment_number")
    commitment_date = _find_extraction(extractions, "property_info", "effective date", "commitment date", "effective_date")
    issued_by = _find_extraction(extractions, "party", "title company", "underwriter", "issuer", "issued by")

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
            "severity": flag.severity,
            "category": flag.flag_type.replace("_", " ").title(),
            "description": flag.title,
            "doc_ref": doc_ref,
            "action": action,
        })

    # Compute counts
    critical_count = sum(1 for f in flags if f.severity == "critical")
    warning_count = sum(1 for f in flags if f.severity in ("high", "medium"))
    review_count = sum(1 for f in flags if f.status in ("open", "escalated"))
    validation_score = round(readiness.score / 10) if readiness else 0

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
        validation_score=validation_score,
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
        for key in ("value", "address", "full_address", "name", "amount", "number", "date", "text"):
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
