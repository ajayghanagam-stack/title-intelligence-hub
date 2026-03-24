"""Weighted readiness scoring matching V2's computeReadinessScore.

Categories with weights:
- requirements (35%): satisfied / total requirements
- endorsements (25%): present / required endorsements
- liens (25%): resolved / total liens
- exceptions (10%): accepted / flagged exceptions
- consistency (5%): cross-section mismatches

Score: weighted average minus penalties for critical/high flags
Status: ready (≥90), at_risk (≥60), not_ready (<60)
Estimated days: critical=4d, high=2d, medium=1d (concurrent paths)
"""

import uuid
import math

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.micro_apps.title_intelligence.models.pack import Pack
from app.micro_apps.title_intelligence.models.extraction import Extraction
from app.micro_apps.title_intelligence.models.flag import Flag
from app.micro_apps.title_intelligence.schemas.readiness import (
    CategoryScore,
    ChecklistItem,
    ReadinessResponse,
)

# Penalty percentage per open flag severity (applied as multiplier reduction)
SEVERITY_PENALTY = {"critical": 0.08, "high": 0.05, "medium": 0.02, "low": 0.005}

# Estimated resolution days per severity (concurrent, so we take max path)
SEVERITY_DAYS = {"critical": 4, "high": 2, "medium": 1, "low": 0}

# Category weights (must sum to 1.0)
CATEGORY_WEIGHTS = {
    "requirements": 0.35,
    "endorsements": 0.25,
    "liens": 0.25,
    "exceptions": 0.10,
    "consistency": 0.05,
}

# Flag type → category mapping
FLAG_CATEGORY_MAP = {
    "requirement_missing_proof": "requirements",
    "missing_endorsement": "endorsements",
    "unresolved_lien": "liens",
    "unacceptable_exception": "exceptions",
    "cross_section_mismatch": "consistency",
}

# Extractions with confidence below this threshold are flagged as "needs_review"
# in the readiness checklist so humans can verify them before relying on them.
CONFIDENCE_THRESHOLD = 0.5


async def calculate_readiness(
    db: AsyncSession, org_id: uuid.UUID, pack_id: uuid.UUID
) -> ReadinessResponse:
    pack = (await db.execute(
        select(Pack).where(Pack.id == pack_id, Pack.org_id == org_id)
    )).scalar_one_or_none()

    # Fetch all extractions
    ext_result = await db.execute(
        select(Extraction).where(
            Extraction.pack_id == pack_id, Extraction.org_id == org_id
        )
    )
    extractions = list(ext_result.scalars().all())

    # Fetch all flags
    flag_result = await db.execute(
        select(Flag).where(Flag.pack_id == pack_id, Flag.org_id == org_id)
    )
    flags = list(flag_result.scalars().all())

    # Build category scores
    categories = _compute_categories(extractions, flags)

    # Weighted average (category scores are 0-100 integers)
    weighted_score = sum(
        cat.score * cat.weight for cat in categories
    )

    # Penalty: each open flag reduces the score by a percentage
    open_flags = [f for f in flags if f.status == "open"]
    penalty_factor = sum(
        SEVERITY_PENALTY.get(f.severity, 0) for f in open_flags
    )
    # Cap total penalty at 60% reduction so the score never collapses to 0
    # when category scores are healthy
    penalty_multiplier = max(0.4, 1.0 - min(penalty_factor, 0.6))
    raw_score = round(weighted_score * penalty_multiplier)
    score = max(0, min(100, raw_score))

    # Status
    if score >= 90:
        status = "ready"
    elif score >= 60:
        status = "at_risk"
    else:
        status = "not_ready"

    # Checklist
    checklist = _build_checklist(extractions, flags)

    # Cross-app: include Title Search flags for linked orders
    ta_category = await _get_title_search_category(db, org_id, pack_id)
    if ta_category:
        categories.append(ta_category)
        # Re-compute weighted score with extra category
        total_weight = sum(c.weight for c in categories)
        if total_weight > 0:
            weighted_score = sum(c.score * c.weight for c in categories) / total_weight * 100
            # Recalculate with TA flags contributing to penalty
            raw_score = round(weighted_score / 100 * penalty_multiplier)
            score = max(0, min(100, raw_score))
            if score >= 90:
                status = "ready"
            elif score >= 60:
                status = "at_risk"
            else:
                status = "not_ready"

    # Estimated days — concurrent paths, so take the max
    estimated_days = _estimate_days(open_flags)

    summary = pack.readiness_summary if pack else None

    return ReadinessResponse(
        score=score,
        status=status,
        summary=summary,
        categories=categories,
        checklist=checklist,
        estimated_days=estimated_days,
    )


def _compute_categories(
    extractions: list, flags: list
) -> list[CategoryScore]:
    """Compute weighted category scores."""

    # Count extractions by type
    ext_by_type: dict[str, list] = {}
    for e in extractions:
        ext_by_type.setdefault(e.extraction_type, []).append(e)

    # Count flags by category
    open_flags_by_cat: dict[str, list] = {cat: [] for cat in CATEGORY_WEIGHTS}
    resolved_flags_by_cat: dict[str, list] = {cat: [] for cat in CATEGORY_WEIGHTS}
    for f in flags:
        cat = FLAG_CATEGORY_MAP.get(f.flag_type, "consistency")
        if f.status == "open":
            open_flags_by_cat[cat].append(f)
        else:
            resolved_flags_by_cat[cat].append(f)

    categories = []

    # 1. Requirements (35%) — satisfied requirements / total requirements
    requirements = ext_by_type.get("requirement", [])
    req_flags = open_flags_by_cat["requirements"]
    total_req = max(len(requirements), 1)
    satisfied_req = max(0, len(requirements) - len(req_flags))
    req_score = satisfied_req / total_req
    categories.append(CategoryScore(
        category="requirements",
        weight=CATEGORY_WEIGHTS["requirements"],
        score=round(req_score * 100),
        max_score=100,
        satisfied=satisfied_req,
        total=total_req,
        details=f"{satisfied_req}/{total_req} requirements satisfied",
    ))

    # 2. Endorsements (25%) — present endorsements vs required (flagged missing)
    endorsements = ext_by_type.get("endorsement", [])
    missing_endorse = open_flags_by_cat["endorsements"]
    total_endorse = len(endorsements) + len(missing_endorse)
    present_endorse = len(endorsements)
    if total_endorse > 0:
        endorse_score = present_endorse / total_endorse
    else:
        endorse_score = 1.0  # No endorsements required = perfect
    categories.append(CategoryScore(
        category="endorsements",
        weight=CATEGORY_WEIGHTS["endorsements"],
        score=round(endorse_score * 100),
        max_score=100,
        satisfied=present_endorse,
        total=total_endorse,
        details=f"{present_endorse}/{total_endorse} endorsements present" if total_endorse > 0 else "No endorsements required",
    ))

    # 3. Liens (25%) — resolved liens / total liens
    lien_flags_open = open_flags_by_cat["liens"]
    lien_flags_resolved = resolved_flags_by_cat["liens"]
    total_liens = len(lien_flags_open) + len(lien_flags_resolved)
    resolved_liens = len(lien_flags_resolved)
    lien_score = resolved_liens / total_liens if total_liens > 0 else 1.0
    categories.append(CategoryScore(
        category="liens",
        weight=CATEGORY_WEIGHTS["liens"],
        score=round(lien_score * 100),
        max_score=100,
        satisfied=resolved_liens,
        total=total_liens,
        details=f"{resolved_liens}/{total_liens} liens resolved" if total_liens > 0 else "No liens identified",
    ))

    # 4. Exceptions (10%) — accepted exceptions / flagged exceptions
    exc_flags_open = open_flags_by_cat["exceptions"]
    exc_flags_resolved = resolved_flags_by_cat["exceptions"]
    total_exc = len(exc_flags_open) + len(exc_flags_resolved)
    accepted_exc = len(exc_flags_resolved)
    exc_score = accepted_exc / total_exc if total_exc > 0 else 1.0
    categories.append(CategoryScore(
        category="exceptions",
        weight=CATEGORY_WEIGHTS["exceptions"],
        score=round(exc_score * 100),
        max_score=100,
        satisfied=accepted_exc,
        total=total_exc,
        details=f"{accepted_exc}/{total_exc} exceptions accepted" if total_exc > 0 else "No exceptions flagged",
    ))

    # 5. Consistency (5%) — cross-section mismatches (fewer = better)
    consistency_open = open_flags_by_cat["consistency"]
    consistency_resolved = resolved_flags_by_cat["consistency"]
    total_consistency = len(consistency_open) + len(consistency_resolved)
    resolved_consistency = len(consistency_resolved)
    consistency_score = 1.0 - (len(consistency_open) / total_consistency) if total_consistency > 0 else 1.0
    categories.append(CategoryScore(
        category="consistency",
        weight=CATEGORY_WEIGHTS["consistency"],
        score=round(consistency_score * 100),
        max_score=100,
        satisfied=resolved_consistency,
        total=total_consistency,
        details=f"{len(consistency_open)} cross-section mismatches" if consistency_open else "No mismatches found",
    ))

    return categories


def _build_checklist(extractions: list, flags: list) -> list[ChecklistItem]:
    """Build a checklist of items grouped by category."""
    items = []

    # Extraction-based checklist items
    ext_types = {"party": "Parties identified", "property_info": "Property info extracted",
                 "requirement": "Requirements extracted", "exception": "Exceptions extracted",
                 "endorsement": "Endorsements identified", "legal_description": "Legal description extracted"}

    ext_by_type: dict[str, list] = {}
    for e in extractions:
        ext_by_type.setdefault(e.extraction_type, []).append(e)

    for ext_type, label in ext_types.items():
        count = len(ext_by_type.get(ext_type, []))
        items.append(ChecklistItem(
            category="extractions",
            label=f"{label} ({count})",
            status="done" if count > 0 else "pending",
        ))

    # Low-confidence extraction items — surface for human review
    low_confidence = [e for e in extractions if e.confidence < CONFIDENCE_THRESHOLD]
    for e in low_confidence:
        items.append(ChecklistItem(
            category="extractions",
            label=f"Low confidence: {e.label} ({e.confidence:.0%})",
            status="needs_review",
        ))

    # Flag-based checklist items
    for f in flags:
        cat = FLAG_CATEGORY_MAP.get(f.flag_type, "consistency")
        if f.status == "open":
            items.append(ChecklistItem(
                category=cat,
                label=f.title,
                status="blocked",
                severity=f.severity,
            ))
        else:
            items.append(ChecklistItem(
                category=cat,
                label=f.title,
                status="done",
                severity=f.severity,
            ))

    return items


def _estimate_days(open_flags: list) -> int:
    """Estimate days to closing readiness based on open flag severities.

    Uses concurrent path model: group flags by severity, take max path.
    critical=4d, high=2d, medium=1d, low=0d
    """
    if not open_flags:
        return 0

    # Group by severity and take max count for concurrent resolution
    severity_counts: dict[str, int] = {}
    for f in open_flags:
        severity_counts[f.severity] = severity_counts.get(f.severity, 0) + 1

    # Each severity level's flags can be worked in parallel within that level,
    # but different severity levels may be sequential (critical first, then high, etc.)
    # Simplified: sum the base days for each severity level that has open flags
    total_days = 0
    for severity, count in severity_counts.items():
        base_days = SEVERITY_DAYS.get(severity, 0)
        if base_days > 0:
            # Concurrent within severity: ceiling of count / 2 (assume 2 parallel workers)
            total_days += base_days * math.ceil(count / 2)

    return max(total_days, 1) if open_flags else 0


async def _get_title_search_category(
    db: AsyncSession, org_id: uuid.UUID, pack_id: uuid.UUID
) -> CategoryScore | None:
    """Query ta_flags for any TSA orders linked to this TI pack.

    Returns a "Title Search" category score, or None if no linked orders exist.
    """
    try:
        from app.micro_apps.title_search.models.order import TAOrder
        from app.micro_apps.title_search.models.flag import TAFlag
    except ImportError:
        return None

    # Find TSA orders linked to this pack
    result = await db.execute(
        select(TAOrder).where(
            TAOrder.linked_pack_id == pack_id,
            TAOrder.org_id == org_id,
        )
    )
    linked_orders = list(result.scalars().all())
    if not linked_orders:
        return None

    # Collect all TSA flags for linked orders
    order_ids = [o.id for o in linked_orders]
    all_ta_flags = []
    for oid in order_ids:
        flag_result = await db.execute(
            select(TAFlag).where(
                TAFlag.order_id == oid,
                TAFlag.org_id == org_id,
            )
        )
        all_ta_flags.extend(flag_result.scalars().all())

    if not all_ta_flags:
        return CategoryScore(
            category="title_search",
            weight=0.0,  # Informational, doesn't affect weighted score
            score=100,
            max_score=100,
            satisfied=0,
            total=0,
            details="No title search flags found",
        )

    open_flags = [f for f in all_ta_flags if f.status == "open"]
    resolved_flags = [f for f in all_ta_flags if f.status != "open"]
    total = len(all_ta_flags)
    resolved = len(resolved_flags)
    score = round((resolved / total) * 100) if total > 0 else 100

    return CategoryScore(
        category="title_search",
        weight=0.0,  # Informational category
        score=score,
        max_score=100,
        satisfied=resolved,
        total=total,
        details=f"{resolved}/{total} title search flags resolved ({len(open_flags)} open)",
    )
