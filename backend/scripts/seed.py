"""
Seed the database with:
  1. Logikality organization + platform admin (super admin — creates customer accounts, manages apps)
  2. The three micro apps (TI, TSA, LO) so they can be assigned to customers
  3. Demo customer accounts with default passwords:
       - Society Title (admin@societytitle.com / password123)
       - Alliance Title Co. (admin@alliancetitle.com / password123)
       - LogikCore (admin@logikcore.com + 6 members @logikcore.com / password123)
  4. Mock county sources for the TSA pipeline

Usage:
    cd backend && PYTHONPATH=. python scripts/seed.py

Idempotent — safe to run multiple times. Existing user passwords are NEVER
overwritten on re-run; the seed password is only the *initial* credential.
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
from app.micro_apps.loan_onboarding.models.doc_type_catalog import LODocTypeCatalog
from app.micro_apps.loan_onboarding.models.extraction_schema import LOExtractionSchema
from app.micro_apps.loan_onboarding.models.validation_rule_org import LOValidationRuleOrg
from app.micro_apps.loan_onboarding.models.program_profile import LOProgramProfile
from app.micro_apps.loan_onboarding.models.global_settings import LOGlobalSettings
from app.models.subscription import Subscription

# Bulk fixture data (extraction schemas, validation rules, program profiles)
# lives in a sibling module so this file stays focused on orchestration.
from scripts.lo_prototype_data import (
    DOC_TYPES as _LO_DOC_TYPES_FIXTURE,
    EXTRACTION_SCHEMAS as LO_PROTOTYPE_EXTRACTION_SCHEMAS,
    VALIDATION_RULES as LO_PROTOTYPE_VALIDATION_RULES,
    PROGRAM_PROFILES as LO_PROTOTYPE_PROGRAM_PROFILES,
    build_default_global_settings as _build_lo_global_settings_defaults,
)

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

LO_APP_NAME = "Loan Onboarding"
LO_APP_SLUG = "loan-onboarding"
LO_APP_DESC = "Mortgage loan package processing — per-page classification, stacking, validation, and HITL review."
LO_APP_ICON = "folder-open"

# Loan Onboarding — prototype doc-type catalog (18 entries).
# Mirrors `prototype/src/mocks/logik-intake-admin.ts` `DOC_TYPES` so each
# LO-subscribed org sees the same starter catalog in the admin UI.
# Tuple shape: (key, name, category, auto_classify_enabled, active)
LO_PROTOTYPE_DOC_TYPES = _LO_DOC_TYPES_FIXTURE


async def seed_lo_doc_types(session: AsyncSession, org_id: uuid.UUID, org_name: str) -> None:
    """Insert the 18 prototype LO doc types for `org_id`, skipping any
    that already exist (matched on `(org_id, key)`)."""
    inserted = 0
    for key, name, category, auto_classify, active in LO_PROTOTYPE_DOC_TYPES:
        result = await session.execute(
            select(LODocTypeCatalog).where(
                LODocTypeCatalog.org_id == org_id,
                LODocTypeCatalog.key == key,
            )
        )
        if result.scalar_one_or_none() is None:
            session.add(LODocTypeCatalog(
                org_id=org_id,
                key=key,
                name=name,
                category=category,
                auto_classify_enabled=auto_classify,
                active=active,
            ))
            inserted += 1
    if inserted:
        print(f"  Seeded {inserted} LO doc types for {org_name}")
    else:
        print(f"  LO doc types already seeded for {org_name}")


async def seed_lo_extraction_schemas(
    session: AsyncSession, org_id: uuid.UUID, org_name: str
) -> None:
    """Insert one extraction-schema row per prototype doc type for the
    org. Idempotent on `(org_id, doc_type_id)`. Requires doc types to
    have been seeded first (FK to ``lo_doc_type_catalog.id``).
    """
    # Build doc-type key → id map for this org
    result = await session.execute(
        select(LODocTypeCatalog.id, LODocTypeCatalog.key).where(
            LODocTypeCatalog.org_id == org_id
        )
    )
    key_to_id: dict[str, uuid.UUID] = {row.key: row.id for row in result}

    inserted = 0
    healed = 0
    for doc_type_key, fields in LO_PROTOTYPE_EXTRACTION_SCHEMAS:
        doc_type_id = key_to_id.get(doc_type_key)
        if doc_type_id is None:
            # Doc type not in catalog (shouldn't happen since we seed
            # them first); skip rather than fail.
            continue
        result = await session.execute(
            select(LOExtractionSchema).where(
                LOExtractionSchema.org_id == org_id,
                LOExtractionSchema.doc_type_id == doc_type_id,
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            session.add(LOExtractionSchema(
                org_id=org_id,
                doc_type_id=doc_type_id,
                fields=list(fields),
                version=1,
                active=True,
            ))
            inserted += 1
        elif not row.fields and fields:
            # Heal a prior seed that left fields=[] (e.g. for schemas
            # that were intentionally seeded as "pending" before we
            # backfilled real field templates). Bump version so the
            # extract cache key changes.
            row.fields = list(fields)
            row.version = (row.version or 1) + 1
            healed += 1
    if inserted:
        print(f"  Seeded {inserted} LO extraction schemas for {org_name}")
    if healed:
        print(f"  Filled fields on {healed} previously-empty schemas for {org_name}")
    if not inserted and not healed:
        print(f"  LO extraction schemas already seeded for {org_name}")


async def seed_lo_validation_rules(
    session: AsyncSession, org_id: uuid.UUID, org_name: str
) -> None:
    """Insert the 14 prototype validation rules for `org_id`. Idempotent
    on `(org_id, scope, rule)`.
    """
    inserted = 0
    healed = 0
    for entry in LO_PROTOTYPE_VALIDATION_RULES:
        result = await session.execute(
            select(LOValidationRuleOrg).where(
                LOValidationRuleOrg.org_id == org_id,
                LOValidationRuleOrg.scope == entry["scope"],
                LOValidationRuleOrg.rule == entry["rule"],
            )
        )
        existing = result.scalar_one_or_none()
        if existing is None:
            session.add(LOValidationRuleOrg(
                org_id=org_id,
                scope=entry["scope"],
                rule=entry["rule"],
                description=entry.get("description", ""),
                applies_to=entry.get("applies_to", ""),
                condition=entry["condition"],
                preset_id=entry["preset_id"],
                severity=entry["severity"],
                active=True,
            ))
            inserted += 1
            continue
        # Heal: backfill the new fields and replace the bundled
        # condition string with the prototype's clean separation.
        changed = False
        if not existing.description and entry.get("description"):
            existing.description = entry["description"]
            changed = True
        if not existing.applies_to and entry.get("applies_to"):
            existing.applies_to = entry["applies_to"]
            changed = True
        if existing.condition != entry["condition"]:
            existing.condition = entry["condition"]
            changed = True
        if changed:
            healed += 1
    if inserted:
        print(f"  Seeded {inserted} LO validation rules for {org_name}")
    if healed:
        print(f"  Healed {healed} LO validation rules for {org_name}")
    if not inserted and not healed:
        print(f"  LO validation rules already seeded for {org_name}")


async def seed_lo_program_profiles(
    session: AsyncSession, org_id: uuid.UUID, org_name: str
) -> None:
    """Insert the 8 prototype program profiles for `org_id`. Idempotent
    on `(org_id, name)`. Two-pass: insert all rows with stacks_with=None,
    then patch investor_overlay rows to point at their base loan program.
    """
    # Pass 1 — insert any missing rows (stacks_with deferred to pass 2)
    inserted = 0
    for profile in LO_PROTOTYPE_PROGRAM_PROFILES:
        result = await session.execute(
            select(LOProgramProfile).where(
                LOProgramProfile.org_id == org_id,
                LOProgramProfile.name == profile["name"],
            )
        )
        if result.scalar_one_or_none() is None:
            session.add(LOProgramProfile(
                org_id=org_id,
                name=profile["name"],
                type=profile["type"],
                stacks_with=None,
                checklist=list(profile["checklist"]),
                extraction_overrides=dict(profile["extraction_overrides"]),
                rule_overrides=list(profile["rule_overrides"]),
                active=profile["active"],
            ))
            inserted += 1
    await session.flush()

    # Pass 2 — resolve stacks_with FKs by name (within this org only) and
    # heal checklist + overrides so previously-seeded rows converge on the
    # latest prototype data (the prototype was authored after the first
    # seed shipped with empty overrides for 7 of 8 profiles).
    result = await session.execute(
        select(LOProgramProfile.id, LOProgramProfile.name).where(
            LOProgramProfile.org_id == org_id
        )
    )
    name_to_id: dict[str, uuid.UUID] = {row.name: row.id for row in result}

    patched = 0
    healed = 0
    for profile in LO_PROTOTYPE_PROGRAM_PROFILES:
        result = await session.execute(
            select(LOProgramProfile).where(
                LOProgramProfile.org_id == org_id,
                LOProgramProfile.name == profile["name"],
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            continue

        # Resolve stacks_with FK (investor_overlay → loan_program).
        target_name = profile.get("stacks_with_name")
        if target_name:
            target_id = name_to_id.get(target_name)
            if target_id is not None and row.stacks_with != target_id:
                row.stacks_with = target_id
                patched += 1

        # Heal pass — replace overrides/checklist if they drifted.
        new_checklist = list(profile["checklist"])
        new_extraction = dict(profile["extraction_overrides"])
        new_rules = list(profile["rule_overrides"])
        if (
            row.checklist != new_checklist
            or row.extraction_overrides != new_extraction
            or row.rule_overrides != new_rules
        ):
            row.checklist = new_checklist
            row.extraction_overrides = new_extraction
            row.rule_overrides = new_rules
            healed += 1

    if inserted:
        print(f"  Seeded {inserted} LO program profiles for {org_name}")
    else:
        print(f"  LO program profiles already seeded for {org_name}")
    if patched:
        print(f"  Linked {patched} investor-overlay → loan-program FKs for {org_name}")
    if healed:
        print(f"  Healed {healed} LO program profile overrides for {org_name}")


async def seed_lo_global_settings(
    session: AsyncSession,
    org_id: uuid.UUID,
    org_name: str,
    org_slug: str,
) -> None:
    """Singleton row per org. Idempotent — skips when present.

    The admin route also auto-creates this row on first GET, so seeding
    is optional; we do it eagerly here so a freshly-seeded dev DB shows
    the prototype values without an additional API call.
    """
    result = await session.execute(
        select(LOGlobalSettings).where(LOGlobalSettings.org_id == org_id)
    )
    existing = result.scalar_one_or_none()
    defaults = _build_lo_global_settings_defaults(
        tenant_slug=org_slug, organization_name=org_name
    )

    if existing is None:
        session.add(LOGlobalSettings(org_id=org_id, **defaults))
        await session.flush()
        print(f"  Seeded LO global settings for {org_name}")
        return

    # Heal: if the stored JSONB shape predates the prototype-faithful
    # restructure (no `sections`/`title`/`items` keys), overwrite with
    # the fresh defaults so the admin UI renders correctly. Detected by
    # presence of the new top-level keys in each column.
    needs_heal = (
        "sections" not in (existing.ai_thresholds or {})
        or "settings" not in (existing.stp_targets or {})
        or "items" not in (existing.roles or {})
        or "items" not in (existing.integrations or {})
        or "settings" not in (existing.tenant or {})
    )
    if needs_heal:
        existing.ai_thresholds = defaults["ai_thresholds"]
        existing.stp_targets = defaults["stp_targets"]
        existing.exception_defaults = defaults["exception_defaults"]
        existing.audit = defaults["audit"]
        existing.roles = defaults["roles"]
        existing.notifications = defaults["notifications"]
        existing.integrations = defaults["integrations"]
        existing.tenant = defaults["tenant"]
        await session.flush()
        print(f"  Healed LO global settings shape for {org_name}")
    else:
        print(f"  LO global settings already seeded for {org_name}")


async def seed_lo_admin_config(
    session: AsyncSession,
    org_id: uuid.UUID,
    org_name: str,
    org_slug: str,
) -> None:
    """One-shot wrapper that seeds the full LO admin config bundle in
    dependency order: doc types → extraction schemas (FK on doc types)
    → validation rules → program profiles → global settings."""
    await seed_lo_doc_types(session, org_id, org_name)
    await session.flush()
    await seed_lo_extraction_schemas(session, org_id, org_name)
    await seed_lo_validation_rules(session, org_id, org_name)
    await seed_lo_program_profiles(session, org_id, org_name)
    await seed_lo_global_settings(session, org_id, org_name, org_slug)


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

    # ── 4b. Loan Onboarding micro app ─────────────────────────
    result = await session.execute(
        select(MicroApp).where(MicroApp.slug == LO_APP_SLUG)
    )
    lo_app = result.scalar_one_or_none()
    if lo_app is None:
        lo_app = MicroApp(
            name=LO_APP_NAME,
            slug=LO_APP_SLUG,
            description=LO_APP_DESC,
            icon=LO_APP_ICON,
        )
        session.add(lo_app)
        await session.flush()
        print(f"  Created micro app: {LO_APP_NAME} (id={lo_app.id})")
    else:
        print(f"  Micro app already exists: {LO_APP_NAME} (id={lo_app.id})")

    # ── 5. Society Title customer account ──────────────────────
    # Create the Society Title org + admin user with subscriptions to both apps
    CUSTOMER_ORG_NAME = "Society Title"
    CUSTOMER_ORG_SLUG = "societytitle"
    CUSTOMER_EMAIL = "admin@societytitle.com"
    CUSTOMER_PASSWORD = "password123"
    CUSTOMER_FULL_NAME = "Society Title Admin"

    result = await session.execute(
        select(Organization).where(Organization.slug == CUSTOMER_ORG_SLUG)
    )
    customer_org = result.scalar_one_or_none()
    if customer_org is None:
        customer_org = Organization(name=CUSTOMER_ORG_NAME, slug=CUSTOMER_ORG_SLUG, logo_url="/society-title-logo.jpeg")
        session.add(customer_org)
        await session.flush()
        print(f"  Created customer org: {CUSTOMER_ORG_NAME} (id={customer_org.id})")
    else:
        # Ensure logo_url is set
        if not customer_org.logo_url:
            customer_org.logo_url = "/society-title-logo.jpeg"
            print(f"  Updated logo for: {CUSTOMER_ORG_NAME}")
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
        # Ensure password is up to date
        from app.services.auth_service import verify_password
        if not verify_password(CUSTOMER_PASSWORD, customer_user.password_hash):
            customer_user.password_hash = hash_password(CUSTOMER_PASSWORD)
            print(f"  Updated customer admin password: {CUSTOMER_FULL_NAME} <{CUSTOMER_EMAIL}>")
        else:
            print(f"  Customer admin already exists: {CUSTOMER_FULL_NAME} <{CUSTOMER_EMAIL}> (id={customer_user.id})")

    # Subscribe Society Title to both micro apps
    for app_obj in [ti_app, ts_app, lo_app]:
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
    await seed_lo_admin_config(session, customer_org.id, CUSTOMER_ORG_NAME, CUSTOMER_ORG_SLUG)
    await session.flush()

    # ── 6. Alliance Title Co. customer account ─────────────────
    ALLIANCE_ORG_NAME = "Alliance Title Co."
    ALLIANCE_ORG_SLUG = "alliancetitle"
    ALLIANCE_EMAIL = "admin@alliancetitle.com"
    ALLIANCE_PASSWORD = "password123"
    ALLIANCE_FULL_NAME = "Jane Smith"

    result = await session.execute(
        select(Organization).where(Organization.slug == ALLIANCE_ORG_SLUG)
    )
    alliance_org = result.scalar_one_or_none()
    if alliance_org is None:
        alliance_org = Organization(name=ALLIANCE_ORG_NAME, slug=ALLIANCE_ORG_SLUG)
        session.add(alliance_org)
        await session.flush()
        print(f"  Created customer org: {ALLIANCE_ORG_NAME} (id={alliance_org.id})")
    else:
        print(f"  Customer org already exists: {ALLIANCE_ORG_NAME} (id={alliance_org.id})")

    result = await session.execute(
        select(User).where(User.email == ALLIANCE_EMAIL)
    )
    alliance_user = result.scalar_one_or_none()
    if alliance_user is None:
        alliance_user_id = uuid.uuid4()
        alliance_user = User(
            id=alliance_user_id,
            auth_user_id=alliance_user_id,
            email=ALLIANCE_EMAIL,
            full_name=ALLIANCE_FULL_NAME,
            password_hash=hash_password(ALLIANCE_PASSWORD),
            org_id=alliance_org.id,
            role="admin",
            is_platform_admin=False,
        )
        session.add(alliance_user)
        await session.flush()
        print(f"  Created customer admin: {ALLIANCE_FULL_NAME} <{ALLIANCE_EMAIL}> (id={alliance_user.id})")
    else:
        # Ensure full_name and password are up to date
        updated = False
        if alliance_user.full_name != ALLIANCE_FULL_NAME:
            alliance_user.full_name = ALLIANCE_FULL_NAME
            updated = True
        from app.services.auth_service import verify_password
        if not verify_password(ALLIANCE_PASSWORD, alliance_user.password_hash):
            alliance_user.password_hash = hash_password(ALLIANCE_PASSWORD)
            updated = True
        if updated:
            print(f"  Updated customer admin: {ALLIANCE_FULL_NAME} <{ALLIANCE_EMAIL}>")
        else:
            print(f"  Customer admin already exists: {ALLIANCE_FULL_NAME} <{ALLIANCE_EMAIL}> (id={alliance_user.id})")

    # Subscribe Alliance Title Co. to both micro apps
    for app_obj in [ti_app, ts_app, lo_app]:
        result = await session.execute(
            select(Subscription).where(
                Subscription.org_id == alliance_org.id,
                Subscription.app_id == app_obj.id,
            )
        )
        if result.scalar_one_or_none() is None:
            session.add(Subscription(
                org_id=alliance_org.id,
                app_id=app_obj.id,
                status="active",
            ))
            print(f"  Subscribed {ALLIANCE_ORG_NAME} to {app_obj.name}")
        else:
            print(f"  Subscription already exists: {ALLIANCE_ORG_NAME} → {app_obj.name}")
    await session.flush()
    await seed_lo_admin_config(session, alliance_org.id, ALLIANCE_ORG_NAME, ALLIANCE_ORG_SLUG)
    await session.flush()

    # ── 6b. LogikCore customer account ────────────────────────
    LOGIKCORE_ORG_NAME = "LogikCore"
    LOGIKCORE_ORG_SLUG = "logikcore"
    LOGIKCORE_LOGO_URL = "/logikcore-primary.svg"
    LOGIKCORE_OWNER_EMAIL = "admin@logikcore.com"
    LOGIKCORE_OWNER_NAME = "Ajay Ghanagam"
    LOGIKCORE_PASSWORD = "password123"
    # (email, full_name) — all share the same default seed password
    LOGIKCORE_MEMBERS = [
        ("ananya@logikcore.com", "Ananya"),
        ("shantanu@logikcore.com", "Shantanu"),
        ("ajay@logikcore.com", "Ajay"),
        ("gautham@logikcore.com", "Gautham"),
        ("malavika@logikcore.com", "Malavika"),
        ("alok@logikcore.com", "Alok"),
    ]

    result = await session.execute(
        select(Organization).where(Organization.slug == LOGIKCORE_ORG_SLUG)
    )
    logikcore_org = result.scalar_one_or_none()
    if logikcore_org is None:
        logikcore_org = Organization(
            name=LOGIKCORE_ORG_NAME,
            slug=LOGIKCORE_ORG_SLUG,
            logo_url=LOGIKCORE_LOGO_URL,
        )
        session.add(logikcore_org)
        await session.flush()
        print(f"  Created customer org: {LOGIKCORE_ORG_NAME} (id={logikcore_org.id})")
    else:
        # Keep logo_url + name in sync with the seed if they were edited away.
        updated = False
        if logikcore_org.logo_url != LOGIKCORE_LOGO_URL:
            logikcore_org.logo_url = LOGIKCORE_LOGO_URL
            updated = True
        if logikcore_org.name != LOGIKCORE_ORG_NAME:
            logikcore_org.name = LOGIKCORE_ORG_NAME
            updated = True
        if updated:
            print(f"  Updated org metadata: {LOGIKCORE_ORG_NAME}")
        else:
            print(f"  Customer org already exists: {LOGIKCORE_ORG_NAME} (id={logikcore_org.id})")

    # Owner
    from app.services.auth_service import verify_password
    result = await session.execute(
        select(User).where(User.email == LOGIKCORE_OWNER_EMAIL)
    )
    logikcore_owner = result.scalar_one_or_none()
    if logikcore_owner is None:
        owner_id = uuid.uuid4()
        logikcore_owner = User(
            id=owner_id,
            auth_user_id=owner_id,
            email=LOGIKCORE_OWNER_EMAIL,
            full_name=LOGIKCORE_OWNER_NAME,
            password_hash=hash_password(LOGIKCORE_PASSWORD),
            org_id=logikcore_org.id,
            role="owner",
            is_platform_admin=False,
        )
        session.add(logikcore_owner)
        await session.flush()
        print(f"  Created customer owner: {LOGIKCORE_OWNER_NAME} <{LOGIKCORE_OWNER_EMAIL}> (id={logikcore_owner.id})")
    else:
        # Don't reset a password the user has already changed — only top up
        # full_name + role. The seed password is the *initial* password only.
        updated = False
        if logikcore_owner.full_name != LOGIKCORE_OWNER_NAME:
            logikcore_owner.full_name = LOGIKCORE_OWNER_NAME
            updated = True
        if logikcore_owner.role != "owner":
            logikcore_owner.role = "owner"
            updated = True
        if updated:
            print(f"  Updated customer owner metadata: {LOGIKCORE_OWNER_EMAIL}")
        else:
            print(f"  Customer owner already exists: {LOGIKCORE_OWNER_EMAIL} (id={logikcore_owner.id})")

    # Members
    for member_email, member_name in LOGIKCORE_MEMBERS:
        result = await session.execute(
            select(User).where(User.email == member_email)
        )
        member = result.scalar_one_or_none()
        if member is None:
            member_id = uuid.uuid4()
            session.add(User(
                id=member_id,
                auth_user_id=member_id,
                email=member_email,
                full_name=member_name,
                password_hash=hash_password(LOGIKCORE_PASSWORD),
                org_id=logikcore_org.id,
                role="member",
                is_platform_admin=False,
            ))
            print(f"  Created member: {member_name} <{member_email}>")
        else:
            # Same policy as owner — don't overwrite passwords that may have
            # been changed; only sync full_name if it's still null.
            if member.full_name is None or member.full_name == "":
                member.full_name = member_name
                print(f"  Set full_name for member: {member_email}")
            else:
                print(f"  Member already exists: {member_email}")
    await session.flush()

    # Subscribe LogikCore to all three micro apps
    for app_obj in [ti_app, ts_app, lo_app]:
        result = await session.execute(
            select(Subscription).where(
                Subscription.org_id == logikcore_org.id,
                Subscription.app_id == app_obj.id,
            )
        )
        if result.scalar_one_or_none() is None:
            session.add(Subscription(
                org_id=logikcore_org.id,
                app_id=app_obj.id,
                status="active",
            ))
            print(f"  Subscribed {LOGIKCORE_ORG_NAME} to {app_obj.name}")
        else:
            print(f"  Subscription already exists: {LOGIKCORE_ORG_NAME} → {app_obj.name}")
    await session.flush()
    await seed_lo_admin_config(session, logikcore_org.id, LOGIKCORE_ORG_NAME, LOGIKCORE_ORG_SLUG)
    await session.flush()

    # ── 7. Seed county sources for testing ──────────────────────
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
