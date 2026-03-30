"""Live benchmark runner — requires GOOGLE_API_KEY and a running database.

Usage:
    cd backend
    python -m benchmarks.run_benchmark --pages 25 50 100

This script:
1. Creates a real pack with a synthetic PDF of the specified page count
2. Runs the full pipeline (ingest → render → examine → complete)
3. Collects metrics from the PipelineRun record
4. Prints a pass/fail report against SLA thresholds

Not used in CI — requires API credentials and real Gemini calls.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid

# Ensure the backend package is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def run_single_benchmark(page_count: int) -> str:
    """Run a benchmark for a document with *page_count* pages.

    Returns a formatted report string.
    """
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

    from app.config import get_settings
    from app.models import Base, ensure_micro_app_models
    from app.micro_apps.title_intelligence.models.pack import Pack, PackFile
    from app.micro_apps.title_intelligence.models.pipeline_run import PipelineRun
    from app.micro_apps.title_intelligence.pipeline.orchestrator import run_pipeline
    from app.micro_apps.title_intelligence.services.storage import get_storage_provider

    from benchmarks.pdf_generator import generate_synthetic_pdf
    from benchmarks.metrics import collect_metrics_from_version_metadata, check_metrics, format_report

    settings = get_settings()
    ensure_micro_app_models()

    engine = create_async_engine(settings.effective_database_url, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    storage = get_storage_provider(settings)

    org_id = uuid.UUID("00000000-0000-0000-0000-000000000010")  # default test org
    pack_id = uuid.uuid4()
    file_id = uuid.uuid4()

    # Generate synthetic PDF and upload
    pdf_bytes = generate_synthetic_pdf(page_count)

    async with session_factory() as db:
        pack = Pack(
            id=pack_id,
            org_id=org_id,
            name=f"Benchmark {page_count}pp",
            status="uploading",
        )
        db.add(pack)

        storage_path = f"{org_id}/{pack_id}/files/benchmark.pdf"
        await storage.put(storage_path, pdf_bytes)

        pack_file = PackFile(
            id=file_id,
            pack_id=pack_id,
            org_id=org_id,
            filename="benchmark.pdf",
            storage_path=storage_path,
            file_size=len(pdf_bytes),
            page_count=page_count,
        )
        db.add(pack_file)
        await db.commit()

    print(f"\n--- Running pipeline for {page_count} pages (pack {pack_id}) ---")

    # Run the full pipeline
    await run_pipeline(pack_id, org_id, session_factory, storage)

    # Collect metrics from PipelineRun
    async with session_factory() as db:
        result = await db.execute(
            select(PipelineRun)
            .where(PipelineRun.pack_id == pack_id, PipelineRun.org_id == org_id)
            .order_by(PipelineRun.started_at.desc())
            .limit(1)
        )
        pipeline_run = result.scalar_one_or_none()

        if pipeline_run is None:
            return f"[{page_count}pp] ERROR: No PipelineRun record found."

        if pipeline_run.status != "completed":
            return (
                f"[{page_count}pp] ERROR: Pipeline {pipeline_run.status}.\n"
                f"  Error: {pipeline_run.error_message or 'unknown'}"
            )

        metrics = collect_metrics_from_version_metadata(
            pipeline_run.version_metadata,
            page_count=page_count,
        )

    sla_result = check_metrics(metrics)
    return format_report(metrics, sla_result)


async def main(page_counts: list[int]) -> int:
    """Run benchmarks for each page count and print results.

    Returns 0 if all pass, 1 if any fail.
    """
    any_failed = False

    for pc in page_counts:
        report = await run_single_benchmark(pc)
        print(report)
        if "FAIL" in report:
            any_failed = True

    # Summary
    print("=" * 60)
    if any_failed:
        print("RESULT: Some benchmarks FAILED SLA thresholds.")
    else:
        print("RESULT: All benchmarks PASSED SLA thresholds.")
    print("=" * 60)

    return 1 if any_failed else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run TI pipeline benchmarks against SLA thresholds")
    parser.add_argument(
        "--pages",
        type=int,
        nargs="+",
        default=[25, 50, 100],
        help="Page counts to benchmark (default: 25 50 100)",
    )
    args = parser.parse_args()

    exit_code = asyncio.run(main(args.pages))
    sys.exit(exit_code)
