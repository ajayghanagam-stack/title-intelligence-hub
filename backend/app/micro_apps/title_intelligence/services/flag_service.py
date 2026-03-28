import uuid
from collections import Counter

from sqlalchemy import select, func, case, asc, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.micro_apps.title_intelligence.models.flag import Flag, Review
from app.micro_apps.title_intelligence.models.extraction import Extraction
from app.core.exceptions import NotFoundError

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


async def list_flags(
    db: AsyncSession,
    org_id: uuid.UUID,
    pack_id: uuid.UUID,
    severity: str | None = None,
    status: str | None = None,
    sort_by: str = "severity",
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Flag], dict[str, int], int]:
    """Return (flags, severity_counts, filtered_total).

    ``counts`` is always computed from all flags (unfiltered) so summary cards
    reflect the full severity breakdown regardless of active filters.
    """
    base = select(Flag).where(Flag.pack_id == pack_id, Flag.org_id == org_id)

    # --- unfiltered counts (always full severity breakdown) ---
    count_result = await db.execute(
        select(Flag.severity, func.count())
        .where(Flag.pack_id == pack_id, Flag.org_id == org_id)
        .group_by(Flag.severity)
    )
    counts = {row[0]: row[1] for row in count_result.all()}

    # --- apply filters ---
    filtered = base
    if severity == "warning":
        filtered = filtered.where(Flag.severity.in_(["high", "medium"]))
    elif severity == "review":
        filtered = filtered.where(Flag.severity == "low")
    elif severity:
        filtered = filtered.where(Flag.severity == severity)
    if status:
        filtered = filtered.where(Flag.status == status)

    # --- filtered total ---
    total_result = await db.execute(
        select(func.count()).select_from(filtered.subquery())
    )
    total = total_result.scalar() or 0

    # --- sorting ---
    if sort_by == "created_at":
        order = desc(Flag.created_at)
    elif sort_by == "flag_type":
        order = asc(Flag.flag_type)
    else:  # "severity" (default)
        order = asc(
            case(SEVERITY_ORDER, value=Flag.severity, else_=99)
        )

    # --- paginated query ---
    result = await db.execute(
        filtered
        .options(selectinload(Flag.reviews))
        .order_by(order, Flag.created_at)
        .limit(limit)
        .offset(offset)
    )
    flags = list(result.scalars().all())
    return flags, counts, total


async def get_flag(
    db: AsyncSession, org_id: uuid.UUID, flag_id: uuid.UUID
) -> Flag | None:
    result = await db.execute(
        select(Flag)
        .options(selectinload(Flag.reviews))
        .where(Flag.id == flag_id, Flag.org_id == org_id)
    )
    return result.scalar_one_or_none()


async def get_flag_for_pack_or_raise(
    db: AsyncSession, org_id: uuid.UUID, pack_id: uuid.UUID, flag_id: uuid.UUID,
) -> Flag:
    """Get a flag ensuring it belongs to the given pack, or raise NotFoundError."""
    flag = await get_flag(db, org_id, flag_id)
    if not flag or flag.pack_id != pack_id:
        raise NotFoundError("Flag", flag_id)
    return flag


async def create_review(
    db: AsyncSession,
    org_id: uuid.UUID,
    flag_id: uuid.UUID,
    reviewer_id: uuid.UUID,
    decision: str,
    reason_code: str = "",
    notes: str | None = None,
) -> Review:
    review = Review(
        flag_id=flag_id,
        org_id=org_id,
        reviewer_id=reviewer_id,
        decision=decision,
        reason_code=reason_code,
        notes=notes,
    )
    db.add(review)

    # Update flag status based on decision
    status_map = {"approve": "approved", "reject": "rejected", "escalate": "escalated"}
    flag = await get_flag(db, org_id, flag_id)
    if flag:
        flag.status = status_map.get(decision, flag.status)

    await db.commit()
    await db.refresh(review)
    return review


async def get_extraction_context(
    db: AsyncSession, org_id: uuid.UUID, pack_id: uuid.UUID,
) -> list[dict]:
    """Fetch extractions as dicts suitable for AI recommendation context."""
    result = await db.execute(
        select(Extraction).where(Extraction.pack_id == pack_id, Extraction.org_id == org_id)
    )
    return [
        {
            "extraction_type": e.extraction_type,
            "label": e.label,
            "value": e.value,
        }
        for e in result.scalars().all()
    ]


async def get_ai_recommendation(
    db: AsyncSession, org_id: uuid.UUID, pack_id: uuid.UUID, flag: Flag,
) -> dict:
    """Get AI-powered review recommendation for a flag."""
    from app.micro_apps.title_intelligence.ai.review_assistant import ReviewAssistant

    extractions = await get_extraction_context(db, org_id, pack_id)
    assistant = ReviewAssistant(org_id)
    return await assistant.recommend(
        flag={
            "title": flag.title,
            "flag_type": flag.flag_type,
            "severity": flag.severity,
            "description": flag.description,
            "ai_explanation": flag.ai_explanation,
            "evidence_refs": flag.evidence_refs,
        },
        extractions=extractions,
    )
