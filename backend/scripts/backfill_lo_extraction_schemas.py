"""Backfill LO doc types and extraction-schema fields for existing orgs.

For every org that has any LO data (doc-type catalog or extraction schema
rows), this script:

  1. Inserts any missing doc types from ``lo_prototype_data.DOC_TYPES``
     into ``lo_doc_type_catalog``.
  2. For each doc type whose extraction-schema row is missing, creates
     it from the template.
  3. For each existing extraction-schema row, appends any missing field
     keys from the template (preserving the existing field rows, including
     their ``required`` and ``min_confidence``). Bumps ``version`` when
     fields were added so cache keys change.

Run after pulling new fixtures into ``lo_prototype_data.py`` to push the
additions into already-seeded dev orgs without recreating them.

Usage:
    cd backend && PYTHONPATH=. python scripts/backfill_lo_extraction_schemas.py
"""
from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.config import get_settings
from app.models import Base  # noqa: F401 — ensures all models register
from app.micro_apps.loan_onboarding.models.doc_type_catalog import LODocTypeCatalog
from app.micro_apps.loan_onboarding.models.extraction_schema import LOExtractionSchema

from scripts.lo_prototype_data import (
    DOC_TYPES as LO_DOC_TYPES,
    EXTRACTION_SCHEMAS as LO_EXTRACTION_SCHEMAS,
)


async def _orgs_with_lo_data(session: AsyncSession) -> list[uuid.UUID]:
    """Return distinct org_ids that have ever held LO catalog/schema rows.

    Using "has rows" rather than "has active subscription" so we cover
    dev orgs that were seeded even if their subscription was later
    detached or deactivated."""
    catalog_orgs = await session.execute(
        select(LODocTypeCatalog.org_id).distinct()
    )
    schema_orgs = await session.execute(
        select(LOExtractionSchema.org_id).distinct()
    )
    ids: set[uuid.UUID] = set()
    for (oid,) in catalog_orgs:
        ids.add(oid)
    for (oid,) in schema_orgs:
        ids.add(oid)
    return sorted(ids, key=str)


async def _ensure_doc_types(
    session: AsyncSession, org_id: uuid.UUID
) -> dict[str, uuid.UUID]:
    """Insert missing doc types from LO_DOC_TYPES; return key→id map."""
    existing = await session.execute(
        select(LODocTypeCatalog.id, LODocTypeCatalog.key).where(
            LODocTypeCatalog.org_id == org_id
        )
    )
    key_to_id: dict[str, uuid.UUID] = {row.key: row.id for row in existing}

    added = 0
    for key, name, category, auto_classify, active in LO_DOC_TYPES:
        if key in key_to_id:
            continue
        row = LODocTypeCatalog(
            org_id=org_id,
            key=key,
            name=name,
            category=category,
            auto_classify_enabled=auto_classify,
            active=active,
        )
        session.add(row)
        added += 1
    if added:
        await session.flush()
        # Re-read to get IDs for the just-inserted rows.
        refreshed = await session.execute(
            select(LODocTypeCatalog.id, LODocTypeCatalog.key).where(
                LODocTypeCatalog.org_id == org_id
            )
        )
        key_to_id = {r.key: r.id for r in refreshed}
        print(f"    + {added} doc types")
    return key_to_id


async def _ensure_schemas(
    session: AsyncSession, org_id: uuid.UUID, key_to_id: dict[str, uuid.UUID]
) -> None:
    """Create/merge extraction-schema rows for each templated doc type."""
    created = 0
    merged = 0
    for doc_type_key, template_fields in LO_EXTRACTION_SCHEMAS:
        doc_type_id = key_to_id.get(doc_type_key)
        if doc_type_id is None:
            # Doc type couldn't be inserted (shouldn't happen) — skip.
            continue
        existing = await session.execute(
            select(LOExtractionSchema).where(
                LOExtractionSchema.org_id == org_id,
                LOExtractionSchema.doc_type_id == doc_type_id,
            )
        )
        row = existing.scalar_one_or_none()
        if row is None:
            session.add(LOExtractionSchema(
                org_id=org_id,
                doc_type_id=doc_type_id,
                fields=list(template_fields),
                version=1,
                active=True,
            ))
            created += 1
            continue

        # Merge: keep existing field rows untouched (preserves user-set
        # required/min_confidence values), append any missing keys from
        # the template.
        existing_keys = {f.get("key") for f in (row.fields or []) if isinstance(f, dict)}
        additions = [
            dict(f) for f in template_fields if f["key"] not in existing_keys
        ]
        if additions:
            row.fields = list(row.fields or []) + additions
            row.version = (row.version or 1) + 1
            merged += 1
    if created:
        print(f"    + {created} extraction schemas (new)")
    if merged:
        print(f"    ~ {merged} extraction schemas (merged missing fields)")
    if not created and not merged:
        print("    = no changes needed")


async def main() -> None:
    settings = get_settings()
    engine = create_async_engine(settings.effective_database_url, echo=False)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        org_ids = await _orgs_with_lo_data(session)
        if not org_ids:
            print("No orgs with LO data found.")
            return

        print(f"Backfilling {len(org_ids)} org(s)…")
        for org_id in org_ids:
            print(f"  org={org_id}")
            key_to_id = await _ensure_doc_types(session, org_id)
            await _ensure_schemas(session, org_id, key_to_id)
        await session.commit()
        print("Done.")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
