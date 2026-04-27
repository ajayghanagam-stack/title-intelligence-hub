"""Merge AI classifications with reviewer-authored overrides into a single
"effective assignment" view.

Downstream stages (stack, validate) should read via this helper, not straight
from `lo_classifications`. That way a reviewer's move of page 5 from W-2 to
Paystub immediately changes how the next re-stack groups pages — without ever
mutating the ML output row.

Override rules:
- If an `LOPageOverride` row exists for a page, its `assigned_doc_type` wins.
- Overridden pages receive confidence 1.0 (human is the oracle).
- `page_role_override` (if set) beats `LOClassification.page_role`; otherwise
  the ML-assigned role is kept so stacker boundaries still respect signals
  like "first_page" that the model picked up on.
- `detected_fields` is never overridden — extractions remain the ML's call.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.micro_apps.loan_onboarding.models.classification import LOClassification
from app.micro_apps.loan_onboarding.models.page_override import LOPageOverride


HUMAN_OVERRIDE_CONFIDENCE = 1.0


@dataclass(frozen=True)
class EffectiveClassification:
    """Merged view of (ML classification + optional reviewer override).

    Consumed by `services.stacking.build_stacks()` and by the validate stage.
    """
    page_id: uuid.UUID
    page_number: int
    doc_type: str
    confidence: float
    page_role: str
    detected_fields: list[dict[str, Any]] = field(default_factory=list)
    is_overridden: bool = False
    original_doc_type: str | None = None
    original_page_role: str | None = None

    # Convenience for feeding into build_stacks (which expects a minimal
    # ClassifiedPage shape — dict with these keys).
    def as_classified_dict(self) -> dict[str, Any]:
        return {
            "page_number": self.page_number,
            "predicted_doc_type": self.doc_type,
            "confidence": self.confidence,
            "page_role": self.page_role,
        }


async def load_effective_classifications(
    db: AsyncSession,
    org_id: uuid.UUID,
    package_id: uuid.UUID,
) -> list[EffectiveClassification]:
    """Load all classifications for a package with any overrides applied.

    Sorted by `page_number` ascending so stacker/validator can rely on order.
    """
    classifications = (
        await db.execute(
            select(LOClassification)
            .where(
                LOClassification.package_id == package_id,
                LOClassification.org_id == org_id,
            )
            .order_by(LOClassification.page_number.asc())
        )
    ).scalars().all()

    overrides = (
        await db.execute(
            select(LOPageOverride).where(
                LOPageOverride.package_id == package_id,
                LOPageOverride.org_id == org_id,
            )
        )
    ).scalars().all()
    overrides_by_page = {o.page_id: o for o in overrides}

    return [
        _merge(clf, overrides_by_page.get(clf.page_id))
        for clf in classifications
    ]


def _merge(
    clf: LOClassification,
    override: LOPageOverride | None,
) -> EffectiveClassification:
    if override is None:
        return EffectiveClassification(
            page_id=clf.page_id,
            page_number=clf.page_number,
            doc_type=clf.predicted_doc_type,
            confidence=clf.confidence,
            page_role=clf.page_role,
            detected_fields=list(clf.detected_fields or []),
            is_overridden=False,
        )
    return EffectiveClassification(
        page_id=clf.page_id,
        page_number=clf.page_number,
        doc_type=override.assigned_doc_type,
        confidence=HUMAN_OVERRIDE_CONFIDENCE,
        page_role=(override.page_role_override or clf.page_role),
        detected_fields=list(clf.detected_fields or []),
        is_overridden=True,
        original_doc_type=clf.predicted_doc_type,
        original_page_role=clf.page_role,
    )


def override_set_hash(overrides: Iterable[LOPageOverride]) -> str:
    """Stable content hash of the active override set.

    Use this in `LOPipelineRun.version_metadata` so future runs replay
    deterministically given the same reviewer state. Sorted by page_id so the
    hash is independent of DB row insertion order.
    """
    import hashlib

    rows = sorted(
        (
            (
                str(o.page_id),
                o.assigned_doc_type,
                o.page_role_override or "",
            )
            for o in overrides
        ),
        key=lambda t: t[0],
    )
    payload = "\n".join(f"{pid}|{dt}|{role}" for pid, dt, role in rows).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
