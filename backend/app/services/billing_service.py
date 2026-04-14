"""Billing service — per-org usage queries for platform admin billing reports."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.micro_app import MicroApp
from app.models.organization import Organization
from app.models.subscription import Subscription


async def get_org_usage(
    db: AsyncSession,
    org_id: uuid.UUID,
    start_date: date,
    end_date: date,
) -> dict:
    """Return per-app usage counts and item details for a single org within a date range.

    Returns: {org_id, org_name, start_date, end_date, apps: [{
        app_slug, app_name, completed_count, total_count,
        items: [{name, filenames?, status, created_at}]
    }]}
    """
    # Verify org exists
    result = await db.execute(select(Organization).where(Organization.id == org_id))
    org = result.scalar_one_or_none()
    if org is None:
        raise NotFoundError("Organization", org_id)

    start_dt = datetime(start_date.year, start_date.month, start_date.day, tzinfo=timezone.utc)
    end_dt = datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59, tzinfo=timezone.utc)

    apps_usage: list[dict] = []

    # TI packs
    try:
        from app.micro_apps.title_intelligence.models.pack import Pack, PackFile

        # Counts
        total_q = await db.execute(
            select(func.count(Pack.id)).where(
                Pack.org_id == org_id,
                Pack.created_at >= start_dt,
                Pack.created_at <= end_dt,
            )
        )
        total_count = total_q.scalar() or 0

        completed_q = await db.execute(
            select(func.count(Pack.id)).where(
                Pack.org_id == org_id,
                Pack.created_at >= start_dt,
                Pack.created_at <= end_dt,
                Pack.status == "completed",
            )
        )
        completed_count = completed_q.scalar() or 0

        # Item details: only completed packs with their uploaded filenames
        packs_q = await db.execute(
            select(Pack).where(
                Pack.org_id == org_id,
                Pack.created_at >= start_dt,
                Pack.created_at <= end_dt,
                Pack.status == "completed",
            ).order_by(Pack.created_at.desc())
        )
        packs = packs_q.scalars().all()

        items: list[dict] = []
        for pack in packs:
            files_q = await db.execute(
                select(PackFile.filename).where(PackFile.pack_id == pack.id)
            )
            filenames = [row[0] for row in files_q.all()]
            items.append({
                "name": pack.name,
                "filenames": filenames,
                "status": pack.status,
                "created_at": pack.created_at.strftime("%Y-%m-%d") if pack.created_at else "",
            })

        apps_usage.append({
            "app_slug": "title-intelligence",
            "app_name": "Title Intelligence",
            "completed_count": completed_count,
            "total_count": total_count,
            "items": items,
        })
    except ImportError:
        pass

    # TSA orders
    try:
        from app.micro_apps.title_search.models.order import TAOrder

        total_q = await db.execute(
            select(func.count(TAOrder.id)).where(
                TAOrder.org_id == org_id,
                TAOrder.created_at >= start_dt,
                TAOrder.created_at <= end_dt,
            )
        )
        total_count = total_q.scalar() or 0

        completed_q = await db.execute(
            select(func.count(TAOrder.id)).where(
                TAOrder.org_id == org_id,
                TAOrder.created_at >= start_dt,
                TAOrder.created_at <= end_dt,
                TAOrder.status == "completed",
            )
        )
        completed_count = completed_q.scalar() or 0

        # Item details: only completed orders with property address
        orders_q = await db.execute(
            select(TAOrder).where(
                TAOrder.org_id == org_id,
                TAOrder.created_at >= start_dt,
                TAOrder.created_at <= end_dt,
                TAOrder.status == "completed",
            ).order_by(TAOrder.created_at.desc())
        )
        orders = orders_q.scalars().all()

        items = []
        for order in orders:
            items.append({
                "name": order.property_address,
                "status": order.status,
                "created_at": order.created_at.strftime("%Y-%m-%d") if order.created_at else "",
            })

        apps_usage.append({
            "app_slug": "title-search",
            "app_name": "Title Search & Abstracting",
            "completed_count": completed_count,
            "total_count": total_count,
            "items": items,
        })
    except ImportError:
        pass

    return {
        "org_id": str(org_id),
        "org_name": org.name,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "apps": apps_usage,
    }


async def get_all_orgs_usage(
    db: AsyncSession,
    start_date: date,
    end_date: date,
) -> list[dict]:
    """Return per-app usage for all customer orgs, sorted by org name."""
    result = await db.execute(
        select(Organization).order_by(Organization.name)
    )
    orgs = result.scalars().all()

    usage_list = []
    for org in orgs:
        usage = await get_org_usage(db, org.id, start_date, end_date)
        usage_list.append(usage)

    return usage_list
