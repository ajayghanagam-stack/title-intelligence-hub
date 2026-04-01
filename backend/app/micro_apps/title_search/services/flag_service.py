import uuid
from collections import Counter

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.micro_apps.title_search.models.flag import TAFlag
from app.micro_apps.title_search.models.review import TAReview
from app.core.exceptions import NotFoundError


SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


async def list_flags(
    db: AsyncSession, org_id: uuid.UUID, order_id: uuid.UUID
) -> tuple[list[TAFlag], dict[str, int]]:
    result = await db.execute(
        select(TAFlag).where(
            TAFlag.order_id == order_id,
            TAFlag.org_id == org_id,
        )
    )
    flags = list(result.scalars().all())
    flags.sort(key=lambda f: SEVERITY_ORDER.get(f.severity, 99))

    open_flags = [f for f in flags if f.status == "open"]
    counts = dict(Counter(f.severity for f in open_flags))
    return flags, counts


async def get_flag_or_raise(
    db: AsyncSession, org_id: uuid.UUID, order_id: uuid.UUID, flag_id: uuid.UUID
) -> TAFlag:
    result = await db.execute(
        select(TAFlag).where(
            TAFlag.id == flag_id,
            TAFlag.order_id == order_id,
            TAFlag.org_id == org_id,
        )
    )
    flag = result.scalar_one_or_none()
    if not flag:
        raise NotFoundError("Flag", flag_id)
    return flag


async def create_flag_review(
    db: AsyncSession,
    org_id: uuid.UUID,
    order_id: uuid.UUID,
    flag_id: uuid.UUID,
    reviewer_id: uuid.UUID,
    decision: str,
    notes: str | None = None,
    corrected_value: dict | None = None,
) -> TAReview:
    review = TAReview(
        org_id=org_id,
        order_id=order_id,
        flag_id=flag_id,
        reviewer_id=reviewer_id,
        decision=decision,
        notes=notes,
        corrected_value=corrected_value,
    )
    db.add(review)

    # Update flag status based on decision
    flag = await get_flag_or_raise(db, org_id, order_id, flag_id)
    if decision == "approve":
        flag.status = "resolved"
    elif decision == "reject":
        flag.status = "rejected"
    elif decision == "correct":
        flag.status = "corrected"

    await db.commit()
    await db.refresh(review)
    return review
