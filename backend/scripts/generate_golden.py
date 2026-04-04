#!/usr/bin/env python3
"""Generate golden fixture files by running the actual TI pipeline on input PDFs.

Sets up a temporary SQLite DB + LocalStorage, seeds minimal ORM records,
runs pipeline stages 1-3 (ingest → render → examine), reads the AI cache
file, and serializes results to golden fixture JSON files.

Usage:
    cd backend
    GOOGLE_API_KEY=<key> python scripts/generate_golden.py                              # all datasets
    GOOGLE_API_KEY=<key> python scripts/generate_golden.py --dataset simple_commitment  # one dataset
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
import uuid
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path

# Ensure backend is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

GOLDEN_DIR = Path(__file__).parent.parent / "tests" / "title_intelligence" / "golden"
DATASETS = ["simple_commitment", "complex_commitment", "large_document"]

# Namespace for deterministic UUIDs
NS = uuid.NAMESPACE_DNS


class DateTimeEncoder(json.JSONEncoder):
    """JSON encoder that handles date and datetime objects."""

    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, date):
            return obj.isoformat()
        return super().default(obj)


def _setup_env(tmp_dir: str) -> None:
    """Set environment variables before importing app modules."""
    db_path = os.path.join(tmp_dir, "golden.db")
    storage_path = os.path.join(tmp_dir, "storage")
    os.makedirs(storage_path, exist_ok=True)

    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"
    os.environ["STORAGE_PROVIDER"] = "local"
    os.environ["STORAGE_PATH"] = storage_path
    os.environ["AI_PROVIDER"] = "gemini"
    os.environ["PIPELINE_MODE"] = "native_pdf"
    os.environ["PIPELINE_BACKEND"] = "background_tasks"
    os.environ["DEBUG"] = "true"
    os.environ["JWT_SECRET"] = "golden-gen-secret"
    # Vertex AI — uses Application Default Credentials
    os.environ["VERTEX_AI"] = "true"
    os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "ti-stage")
    os.environ.setdefault("GOOGLE_CLOUD_REGION", "us-central1")


def _compute_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


async def generate_dataset(dataset_name: str, tmp_dir: str) -> None:
    """Run pipeline on one golden dataset and write fixture files."""
    dataset_dir = GOLDEN_DIR / dataset_name
    pdf_path = dataset_dir / "input.pdf"

    if not pdf_path.exists():
        print(f"  SKIP {dataset_name}: input.pdf not found at {pdf_path}")
        return

    pdf_bytes = pdf_path.read_bytes()
    pdf_sha256 = _compute_sha256(pdf_bytes)

    # --- Lazy imports (after env setup) ---
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

    from app.config import get_settings
    from app.models import Base, ensure_micro_app_models
    from app.models.organization import Organization
    from app.models.user import User
    from app.models.micro_app import MicroApp
    from app.models.subscription import Subscription
    from app.micro_apps.title_intelligence.models.pack import Pack, PackFile
    from app.micro_apps.title_intelligence.pipeline.stages import (
        stage_ingest,
        stage_render,
        stage_examine,
    )
    from app.micro_apps.title_intelligence.pipeline.version_tracker import (
        collect_version_info,
    )
    from app.micro_apps.title_intelligence.services.chain_builder import build_chain
    from app.services.storage import LocalStorage

    settings = get_settings()

    # Deterministic UUIDs from dataset name
    org_id = uuid.uuid5(NS, f"{dataset_name}.org")
    user_id = uuid.uuid5(NS, f"{dataset_name}.user")
    app_id = uuid.uuid5(NS, f"{dataset_name}.app")
    sub_id = uuid.uuid5(NS, f"{dataset_name}.sub")
    pack_id = uuid.uuid5(NS, f"{dataset_name}.pack")
    file_id = uuid.uuid5(NS, f"{dataset_name}.file")

    # Setup DB
    ensure_micro_app_models()
    db_path = os.path.join(tmp_dir, f"golden_{dataset_name}.db")
    db_url = f"sqlite+aiosqlite:///{db_path}"
    engine = create_async_engine(db_url, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Setup storage
    storage_path = os.path.join(tmp_dir, "storage", dataset_name)
    os.makedirs(storage_path, exist_ok=True)
    storage = LocalStorage(base_path=storage_path)

    # Copy PDF to storage
    pdf_storage_path = f"{org_id}/{pack_id}/files/input.pdf"
    await storage.save(pdf_storage_path, pdf_bytes)

    # Seed data
    async with session_factory() as db:
        db.add(Organization(id=org_id, name="golden-gen", slug="golden-gen"))
        db.add(User(
            id=user_id,
            auth_user_id=user_id,
            org_id=org_id,
            email="golden@test.com",
            full_name="Golden Gen",
            role="owner",
        ))
        db.add(MicroApp(
            id=app_id,
            name="Title Intelligence",
            slug="title-intelligence",
            description="Golden gen",
            icon="file-search",
        ))
        db.add(Subscription(
            id=sub_id,
            org_id=org_id,
            app_id=app_id,
            status="active",
            purchased_at=datetime.now(timezone.utc),
            enabled_at=datetime.now(timezone.utc),
        ))
        db.add(Pack(
            id=pack_id,
            org_id=org_id,
            name=dataset_name,
            status="uploading",
        ))
        db.add(PackFile(
            id=file_id,
            pack_id=pack_id,
            org_id=org_id,
            filename="input.pdf",
            storage_path=pdf_storage_path,
            file_size=len(pdf_bytes),
            content_hash=pdf_sha256,
        ))
        await db.commit()

    # Run pipeline stages
    t0 = time.monotonic()

    print(f"  Running stage_ingest...")
    async with session_factory() as db:
        await stage_ingest(pack_id, org_id, db, storage)

    print(f"  Running stage_render...")
    async with session_factory() as db:
        await stage_render(pack_id, org_id, db, storage)

    print(f"  Running stage_examine...")
    async with session_factory() as db:
        await stage_examine(pack_id, org_id, db, storage)

    elapsed = time.monotonic() - t0
    print(f"  Pipeline completed in {elapsed:.1f}s")

    # Find the AI cache file
    cache_dir = Path(storage_path) / str(org_id) / "ai_cache" / "examiner_native"
    cache_data = None

    if cache_dir.exists():
        cache_files = list(cache_dir.glob("v_*.json"))
        if cache_files:
            # Use the most recently modified cache file
            cache_file = max(cache_files, key=lambda f: f.stat().st_mtime)
            print(f"  Reading cache file: {cache_file.name}")
            cache_data = json.loads(cache_file.read_text())

    if cache_data is None:
        # Try legacy cache path
        cache_dir_legacy = Path(storage_path) / str(org_id) / "ai_cache" / "examiner"
        if cache_dir_legacy.exists():
            cache_files = list(cache_dir_legacy.glob("v_*.json"))
            if cache_files:
                cache_file = max(cache_files, key=lambda f: f.stat().st_mtime)
                print(f"  Reading legacy cache file: {cache_file.name}")
                cache_data = json.loads(cache_file.read_text())

    if cache_data is None:
        print(f"  ERROR: No AI cache file found. Cannot extract results.")
        return

    # Extract results from cache
    triage = cache_data.get("page_types", [])
    transcriptions = cache_data.get("page_transcriptions", [])
    sections = cache_data.get("sections", [])
    extractions = cache_data.get("extractions", [])
    flags_raw = cache_data.get("flags_raw", [])
    flags_normalized = cache_data.get("flags", [])

    # Build chain from extractions
    chain_result = build_chain(extractions)
    chain_dict = asdict(chain_result)

    # Collect version info for metadata
    version_info = collect_version_info(settings)

    # Count total pages from triage data
    total_pages = len(triage) if triage else 0
    if total_pages == 0:
        # Fall back to DB query
        from app.micro_apps.title_intelligence.models.page import Page
        from sqlalchemy import select, func
        async with session_factory() as db:
            result = await db.execute(
                select(func.count()).where(Page.pack_id == pack_id, Page.org_id == org_id)
            )
            total_pages = result.scalar() or 0

    # Compute token totals from transcriptions (rough proxy)
    total_input_tokens = 0
    total_output_tokens = 0

    # Read existing metadata to preserve human-written fields
    existing_metadata_path = dataset_dir / "metadata.json"
    existing_metadata = {}
    if existing_metadata_path.exists():
        existing_metadata = json.loads(existing_metadata_path.read_text())

    # Build metadata
    metadata = {
        "name": dataset_name,
        "description": existing_metadata.get("description", f"{total_pages}-page title commitment"),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "pdf_filename": existing_metadata.get("pdf_filename", "input.pdf"),
        "total_pages": total_pages,
        "pdf_sha256": pdf_sha256,
        "ai_provider": version_info.get("ai_platform", "gemini"),
        "ai_model": version_info.get("ai_model", ""),
        "pipeline_mode": settings.PIPELINE_MODE,
        "ingestion_prompt_hash": version_info.get("ingestion_prompt_hash", ""),
        "extraction_tool_hash": version_info.get("extraction_tool_hash", ""),
        "flag_rules_version": version_info.get("flag_rules_version", ""),
        "chain_builder_version": version_info.get("chain_builder_version", ""),
        "normalizer_version": version_info.get("normalizer_version", ""),
        "triage_prompt_hash": version_info.get("triage_prompt_hash", ""),
        "extraction_registry_hash": version_info.get("extraction_registry_hash", ""),
        "triage_enabled": settings.TRIAGE_ENABLED,
        "grouping_enabled": settings.GROUPING_ENABLED,
        "specialized_extraction": settings.SPECIALIZED_EXTRACTION_ENABLED,
        "total_elapsed_seconds": round(elapsed, 2),
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
        "extra": {
            **existing_metadata.get("extra", {}),
            "note": "Generated by scripts/generate_golden.py",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": existing_metadata.get("extra", {}).get("source", "input.pdf"),
        },
    }

    # Write golden files
    def _write(filename: str, data) -> None:
        path = dataset_dir / filename
        with open(path, "w") as f:
            json.dump(data, f, indent=2, cls=DateTimeEncoder)
        print(f"  Wrote {filename} ({_size_desc(data)})")

    def _size_desc(data) -> str:
        if isinstance(data, list):
            return f"{len(data)} items"
        if isinstance(data, dict):
            return f"{len(data)} keys"
        return "?"

    _write("metadata.json", metadata)
    _write("triage.json", triage)
    _write("transcriptions.json", transcriptions)
    _write("sections.json", sections)
    _write("extractions.json", extractions)
    _write("flags_raw.json", flags_raw)
    _write("flags_normalized.json", flags_normalized)
    _write("chain.json", chain_dict)

    # Cleanup engine
    await engine.dispose()

    print(f"  Done: {len(extractions)} extractions, {len(flags_normalized)} flags, "
          f"{len(sections)} sections, {len(transcriptions)} transcriptions")


async def main(datasets: list[str]) -> int:
    """Run golden generation for each dataset."""
    tmp_dir = tempfile.mkdtemp(prefix="golden_gen_")
    print(f"Working directory: {tmp_dir}")

    try:
        for ds in datasets:
            print(f"\n{'='*60}")
            print(f"Generating golden set: {ds}")
            print(f"{'='*60}")

            # Clear settings cache between datasets
            from app.config import get_settings
            get_settings.cache_clear()

            # Re-apply env setup (tmp_dir stays the same)
            _setup_env(tmp_dir)

            try:
                await generate_dataset(ds, tmp_dir)
            except Exception as e:
                print(f"  FAILED: {e}")
                import traceback
                traceback.print_exc()
                return 1

    finally:
        # Cleanup temp directory
        shutil.rmtree(tmp_dir, ignore_errors=True)
        print(f"\nCleaned up {tmp_dir}")

    print(f"\nAll golden sets generated successfully.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate golden fixture files from actual pipeline runs"
    )
    parser.add_argument(
        "--dataset",
        choices=DATASETS,
        help="Generate for a single dataset (default: all)",
    )
    args = parser.parse_args()

    # Setup env before any app imports
    tmp_dir = tempfile.mkdtemp(prefix="golden_gen_pre_")
    _setup_env(tmp_dir)

    datasets = [args.dataset] if args.dataset else DATASETS

    exit_code = asyncio.run(main(datasets))
    # Clean up the pre-setup tmpdir
    shutil.rmtree(tmp_dir, ignore_errors=True)
    sys.exit(exit_code)
