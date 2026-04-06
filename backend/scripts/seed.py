"""
Seed the database with:
  1. Logikality organization (platform admin's home org)
  2. Logikality Admin user (platform super admin — creates customer accounts, manages apps)
  3. Title Intelligence micro app (available for admin to assign to customers)

The Logikality Admin does NOT subscribe to any micro app.
He is the super admin who creates and manages customer accounts.

Usage:
    cd backend && PYTHONPATH=. python scripts/seed.py

Idempotent — safe to run multiple times.
"""

import asyncio
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.config import get_settings
from app.models import Base  # noqa: F401  — ensures all models are imported
from app.models.organization import Organization
from app.models.user import User
from app.models.micro_app import MicroApp
from app.services.auth_service import hash_password
from app.micro_apps.title_search.models.county_source import TACountySource
from app.models.subscription import Subscription

# ── Seed constants ──────────────────────────────────────────────
ADMIN_EMAIL = "admin@logikality.com"
ADMIN_PASSWORD = "admin123"  # Change after first login
ADMIN_FULL_NAME = "Logikality Admin"

ORG_NAME = "Logikality"
ORG_SLUG = "logikality"

TI_APP_NAME = "Title Intelligence"
TI_APP_SLUG = "title-intelligence"
TI_APP_DESC = "AI-powered title document analysis — extractions, risk flags, readiness scores, and reports."
TI_APP_ICON = "file-search"

TS_APP_NAME = "Title Search & Abstracting"
TS_APP_SLUG = "title-search"
TS_APP_DESC = "Automated county record searches, chain-of-title construction, and abstract package generation."
TS_APP_ICON = "search"


async def seed(session: AsyncSession) -> None:
    # ── 1. Logikality organization ──────────────────────────────
    result = await session.execute(
        select(Organization).where(Organization.slug == ORG_SLUG)
    )
    org = result.scalar_one_or_none()
    if org is None:
        org = Organization(name=ORG_NAME, slug=ORG_SLUG)
        session.add(org)
        await session.flush()
        print(f"  Created organization: {ORG_NAME} (id={org.id})")
    else:
        print(f"  Organization already exists: {ORG_NAME} (id={org.id})")

    # ── 2. Logikality Admin (platform super admin) ──────────────
    result = await session.execute(
        select(User).where(User.email == ADMIN_EMAIL, User.org_id == org.id)
    )
    user = result.scalar_one_or_none()
    if user is None:
        user_id = uuid.uuid4()
        user = User(
            id=user_id,
            auth_user_id=user_id,
            org_id=org.id,
            email=ADMIN_EMAIL,
            full_name=ADMIN_FULL_NAME,
            password_hash=hash_password(ADMIN_PASSWORD),
            role="owner",
            is_platform_admin=True,
        )
        session.add(user)
        await session.flush()
        print(f"  Created platform admin: {ADMIN_FULL_NAME} <{ADMIN_EMAIL}> (id={user.id})")
    else:
        # Ensure existing user has platform admin flag
        if not user.is_platform_admin:
            user.is_platform_admin = True
            print(f"  Updated user to platform admin: {ADMIN_FULL_NAME}")
        else:
            print(f"  Platform admin already exists: {ADMIN_FULL_NAME} <{ADMIN_EMAIL}> (id={user.id})")

    # ── 3. Title Intelligence micro app ─────────────────────────
    # Seeded so the admin can assign it to customer accounts.
    # No subscription is created for the Logikality org itself.
    result = await session.execute(
        select(MicroApp).where(MicroApp.slug == TI_APP_SLUG)
    )
    ti_app = result.scalar_one_or_none()
    if ti_app is None:
        ti_app = MicroApp(
            name=TI_APP_NAME,
            slug=TI_APP_SLUG,
            description=TI_APP_DESC,
            icon=TI_APP_ICON,
        )
        session.add(ti_app)
        await session.flush()
        print(f"  Created micro app: {TI_APP_NAME} (id={ti_app.id})")
    else:
        print(f"  Micro app already exists: {TI_APP_NAME} (id={ti_app.id})")

    # ── 4. Title Search & Abstracting micro app ───────────────
    result = await session.execute(
        select(MicroApp).where(MicroApp.slug == TS_APP_SLUG)
    )
    ts_app = result.scalar_one_or_none()
    if ts_app is None:
        ts_app = MicroApp(
            name=TS_APP_NAME,
            slug=TS_APP_SLUG,
            description=TS_APP_DESC,
            icon=TS_APP_ICON,
        )
        session.add(ts_app)
        await session.flush()
        print(f"  Created micro app: {TS_APP_NAME} (id={ts_app.id})")
    else:
        print(f"  Micro app already exists: {TS_APP_NAME} (id={ts_app.id})")

    # ── 5. Society Title customer account ──────────────────────
    # Create the Society Title org + admin user with subscriptions to both apps
    CUSTOMER_ORG_NAME = "Society Title"
    CUSTOMER_ORG_SLUG = "societytitle"
    CUSTOMER_EMAIL = "admin@societytitle.com"
    CUSTOMER_PASSWORD = "admin123"
    CUSTOMER_FULL_NAME = "Society Title Admin"

    result = await session.execute(
        select(Organization).where(Organization.slug == CUSTOMER_ORG_SLUG)
    )
    customer_org = result.scalar_one_or_none()
    if customer_org is None:
        customer_org = Organization(name=CUSTOMER_ORG_NAME, slug=CUSTOMER_ORG_SLUG)
        session.add(customer_org)
        await session.flush()
        print(f"  Created customer org: {CUSTOMER_ORG_NAME} (id={customer_org.id})")
    else:
        print(f"  Customer org already exists: {CUSTOMER_ORG_NAME} (id={customer_org.id})")

    result = await session.execute(
        select(User).where(User.email == CUSTOMER_EMAIL)
    )
    customer_user = result.scalar_one_or_none()
    if customer_user is None:
        customer_user_id = uuid.uuid4()
        customer_user = User(
            id=customer_user_id,
            auth_user_id=customer_user_id,
            email=CUSTOMER_EMAIL,
            full_name=CUSTOMER_FULL_NAME,
            password_hash=hash_password(CUSTOMER_PASSWORD),
            org_id=customer_org.id,
            role="admin",
            is_platform_admin=False,
        )
        session.add(customer_user)
        await session.flush()
        print(f"  Created customer admin: {CUSTOMER_FULL_NAME} <{CUSTOMER_EMAIL}> (id={customer_user.id})")
    else:
        print(f"  Customer admin already exists: {CUSTOMER_FULL_NAME} <{CUSTOMER_EMAIL}> (id={customer_user.id})")

    # Subscribe Society Title to both micro apps
    for app_obj in [ti_app, ts_app]:
        result = await session.execute(
            select(Subscription).where(
                Subscription.org_id == customer_org.id,
                Subscription.app_id == app_obj.id,
            )
        )
        if result.scalar_one_or_none() is None:
            session.add(Subscription(
                org_id=customer_org.id,
                app_id=app_obj.id,
                status="active",
            ))
            print(f"  Subscribed {CUSTOMER_ORG_NAME} to {app_obj.name}")
        else:
            print(f"  Subscription already exists: {CUSTOMER_ORG_NAME} → {app_obj.name}")
    await session.flush()

    # ── 6. Seed county sources for testing ──────────────────────
    # Create digital county sources so the TSA pipeline can run end-to-end.
    test_counties = [
        ("Cook", "IL"),
        ("Los Angeles", "CA"),
        ("Harris", "TX"),
        ("Maricopa", "AZ"),
    ]
    source_types = ["recorder", "clerk", "assessor"]

    for county, state_code in test_counties:
        for source_type in source_types:
            result = await session.execute(
                select(TACountySource).where(
                    TACountySource.county == county,
                    TACountySource.state_code == state_code,
                    TACountySource.source_type == source_type,
                )
            )
            if result.scalar_one_or_none() is None:
                session.add(TACountySource(
                    county=county,
                    state_code=state_code,
                    source_type=source_type,
                    availability="digital",
                    portal_type="api",
                    portal_url=f"https://mock.{county.lower().replace(' ', '')}.{state_code.lower()}.gov/{source_type}",
                    search_config={"type": "mock", "version": "1.0"},
                    is_active=True,
                ))
    await session.flush()
    print(f"  County sources seeded for: {', '.join(f'{c} {s}' for c, s in test_counties)}")

    await session.commit()


async def main() -> None:
    settings = get_settings()
    engine = create_async_engine(settings.effective_database_url, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    print("Seeding database...")
    async with session_factory() as session:
        await seed(session)

    print("\nDone! Platform admin credentials:")
    print(f"  Email:    {ADMIN_EMAIL}")
    print(f"  Password: {ADMIN_PASSWORD}")
    print("\nUse POST /api/v1/admin/accounts to create customer accounts.")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
