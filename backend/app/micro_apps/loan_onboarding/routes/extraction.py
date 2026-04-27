"""Extraction routes — list per-stack extracted fields."""
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_member, get_db, get_org_id
from app.micro_apps.loan_onboarding.models.extraction import LOExtraction
from app.micro_apps.loan_onboarding.models.stack import LOStack
from app.micro_apps.loan_onboarding.services import package_service
from app.models.user import User

router = APIRouter()


@router.get("/packages/{package_id}/extractions")
async def list_extractions(
    package_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    """Return one row per stack with the extracted fields the agent emitted.

    The frontend consumes this for both:
    - the per-stack 'Extracted fields' panel inside each expanded stack card
    - the dashboard 'Extracted fields' download card (JSON / CSV / MISMO XML)
    """
    pkg = await package_service.get_package_or_raise(db, org_id, package_id)

    rows = (await db.execute(
        select(LOExtraction).where(
            LOExtraction.package_id == package_id,
            LOExtraction.org_id == org_id,
        )
    )).scalars().all()

    # Pull stack_index for stable client-side ordering and labels.
    stacks = (await db.execute(
        select(LOStack).where(
            LOStack.package_id == package_id,
            LOStack.org_id == org_id,
        )
    )).scalars().all()
    stack_index_by_id = {s.id: s.stack_index for s in stacks}

    out: list[dict] = []
    for r in rows:
        flattened: list[dict] = []
        for f in (r.fields or []):
            if not isinstance(f, dict):
                continue
            loc = f.get("location")
            page = None
            bbox = None
            if isinstance(loc, dict):
                try:
                    page = int(loc.get("page")) if loc.get("page") is not None else None
                except (TypeError, ValueError):
                    page = None
                box = loc.get("bbox")
                if isinstance(box, list) and len(box) == 4:
                    try:
                        bbox = [float(x) for x in box]
                    except (TypeError, ValueError):
                        bbox = None
            flattened.append({
                "name": str(f.get("name", "")),
                "value": str(f.get("value") or ""),
                "confidence": float(f.get("confidence", 0.0) or 0.0),
                "status": str(f.get("status") or "missing"),
                "page": page,
                "bbox": bbox,
            })
        out.append({
            "stack_id": str(r.stack_id),
            "stack_index": stack_index_by_id.get(r.stack_id, 0),
            "doc_type": r.doc_type,
            "fields": flattened,
            "located_count": int(r.located_count or 0),
            "total_count": int(r.total_count or 0),
        })

    out.sort(key=lambda row: row["stack_index"])
    return {
        "package_id": str(pkg.id),
        "extraction_enabled": bool(pkg.extraction_enabled),
        "stacks": out,
    }
