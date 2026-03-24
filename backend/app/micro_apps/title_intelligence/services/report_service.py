"""Report generation service supporting text, markdown, PDF, and JSON formats."""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.micro_apps.title_intelligence.models.extraction import Extraction
from app.micro_apps.title_intelligence.models.flag import Flag
from app.micro_apps.title_intelligence.models.pack import Pack
from app.micro_apps.title_intelligence.services.readiness_service import calculate_readiness
from app.micro_apps.title_intelligence.services.storage import StorageProvider
from app.micro_apps.title_intelligence.ai.report_agent import ReportAgent
from app.core.exceptions import ForbiddenError, NotFoundError

logger = logging.getLogger(__name__)

AUDIENCES = ["attorney", "lender", "buyer", "underwriter"]


async def generate_report(
    db: AsyncSession,
    org_id: uuid.UUID,
    pack_id: uuid.UUID,
    audience: str,
    format: str = "text",
    storage: StorageProvider | None = None,
) -> dict:
    """Generate a report in the specified format.

    Returns: {"content": str, "uri": str | None}
    - For text/markdown: content is the report text, uri is None
    - For pdf/json: content is a summary, uri is the storage path

    Reports are cached in storage by audience+format so repeat downloads
    skip the AI generation call.
    """
    from app.micro_apps.title_intelligence.services.pdf_service import markdown_to_pdf

    # Check cache first for downloadable formats
    if storage and format in ("pdf", "json"):
        ext = "pdf" if format == "pdf" else "json"
        cached_uri = storage.make_report_path(org_id, pack_id, f"report_{audience}.{ext}")
        try:
            if await storage.exists(cached_uri):
                logger.info("Serving cached report: %s", cached_uri)
                if format == "pdf":
                    pdf_data = await storage.read(cached_uri)
                    return {"content": "", "uri": cached_uri, "_pdf_bytes": pdf_data}
                else:
                    json_data = await storage.read(cached_uri)
                    return {"content": json_data.decode("utf-8"), "uri": cached_uri}
        except Exception:
            logger.debug("Cache miss or read error for %s, regenerating", cached_uri)

    # Gather all data (prefetch pattern)
    pack = (await db.execute(
        select(Pack).where(Pack.id == pack_id, Pack.org_id == org_id)
    )).scalar_one()

    ext_result = await db.execute(
        select(Extraction).where(Extraction.pack_id == pack_id, Extraction.org_id == org_id)
    )
    extractions = list(ext_result.scalars().all())

    flag_result = await db.execute(
        select(Flag).where(Flag.pack_id == pack_id, Flag.org_id == org_id)
    )
    flags = list(flag_result.scalars().all())

    readiness = await calculate_readiness(db, org_id, pack_id)

    agent = ReportAgent(org_id)

    if format == "json":
        # Structured JSON report
        structured = await agent.generate_structured(
            pack_name=pack.name,
            audience=audience,
            extractions=extractions,
            flags=flags,
            readiness_score=readiness.score,
            readiness_summary=readiness.summary,
        )

        # Add metadata
        report_data = {
            "metadata": {
                "pack_name": pack.name,
                "audience": audience,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "readiness_score": readiness.score,
                "readiness_status": readiness.status,
            },
            "report": structured,
        }

        json_bytes = json.dumps(report_data, indent=2).encode("utf-8")

        if storage:
            uri = storage.make_report_path(org_id, pack_id, f"report_{audience}.json")
            await storage.put_object(uri, json_bytes, content_type="application/json")
            return {"content": json.dumps(report_data), "uri": uri}

        return {"content": json.dumps(report_data), "uri": None}

    elif format == "pdf":
        # Generate markdown first, then convert to PDF
        markdown_content = await agent.generate(
            pack_name=pack.name,
            audience=audience,
            format="markdown",
            extractions=extractions,
            flags=flags,
            readiness_score=readiness.score,
            readiness_summary=readiness.summary,
        )

        pdf_bytes = markdown_to_pdf(
            markdown_content,
            title=f"Title Report - {audience.title()} - {pack.name}",
        )

        if storage:
            uri = storage.make_report_path(org_id, pack_id, f"report_{audience}.pdf")
            await storage.put_object(uri, pdf_bytes, content_type="application/pdf")
            return {"content": markdown_content, "uri": uri}

        return {"content": markdown_content, "uri": None, "_pdf_bytes": pdf_bytes}

    else:
        # Text or markdown
        content = await agent.generate(
            pack_name=pack.name,
            audience=audience,
            format=format,
            extractions=extractions,
            flags=flags,
            readiness_score=readiness.score,
            readiness_summary=readiness.summary,
        )
        return {"content": content, "uri": None}


async def pregenerate_reports(
    db: AsyncSession,
    org_id: uuid.UUID,
    pack_id: uuid.UUID,
    storage: StorageProvider,
) -> None:
    """Pre-generate PDF and JSON reports for all audiences.

    Called during pipeline completion so downloads are instant.
    Generates all audiences in parallel (2 AI calls per audience: markdown + structured).
    """
    from app.micro_apps.title_intelligence.services.pdf_service import markdown_to_pdf

    # Prefetch all data once
    pack = (await db.execute(
        select(Pack).where(Pack.id == pack_id, Pack.org_id == org_id)
    )).scalar_one()

    ext_result = await db.execute(
        select(Extraction).where(Extraction.pack_id == pack_id, Extraction.org_id == org_id)
    )
    extractions = list(ext_result.scalars().all())

    flag_result = await db.execute(
        select(Flag).where(Flag.pack_id == pack_id, Flag.org_id == org_id)
    )
    flags = list(flag_result.scalars().all())

    readiness = await calculate_readiness(db, org_id, pack_id)
    agent = ReportAgent(org_id)

    async def _generate_for_audience(audience: str) -> None:
        try:
            # Generate markdown (used for PDF) and structured JSON in parallel
            markdown_task = agent.generate(
                pack_name=pack.name,
                audience=audience,
                format="markdown",
                extractions=extractions,
                flags=flags,
                readiness_score=readiness.score,
                readiness_summary=readiness.summary,
            )
            structured_task = agent.generate_structured(
                pack_name=pack.name,
                audience=audience,
                extractions=extractions,
                flags=flags,
                readiness_score=readiness.score,
                readiness_summary=readiness.summary,
            )

            markdown_content, structured = await asyncio.gather(markdown_task, structured_task)

            # Save PDF
            pdf_bytes = markdown_to_pdf(
                markdown_content,
                title=f"Title Report - {audience.title()} - {pack.name}",
            )
            pdf_uri = storage.make_report_path(org_id, pack_id, f"report_{audience}.pdf")
            await storage.put_object(pdf_uri, pdf_bytes, content_type="application/pdf")

            # Save JSON
            report_data = {
                "metadata": {
                    "pack_name": pack.name,
                    "audience": audience,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "readiness_score": readiness.score,
                    "readiness_status": readiness.status,
                },
                "report": structured,
            }
            json_bytes = json.dumps(report_data, indent=2).encode("utf-8")
            json_uri = storage.make_report_path(org_id, pack_id, f"report_{audience}.json")
            await storage.put_object(json_uri, json_bytes, content_type="application/json")

            logger.info("Pre-generated reports for audience=%s pack=%s", audience, pack_id)
        except Exception:
            logger.warning("Failed to pre-generate %s report for pack %s", audience, pack_id, exc_info=True)

    # Run all audiences in parallel
    await asyncio.gather(*[_generate_for_audience(a) for a in AUDIENCES])
    logger.info("All reports pre-generated for pack %s", pack_id)


async def get_report_by_uri_or_raise(
    org_id: uuid.UUID,
    pack_id: uuid.UUID,
    uri: str,
    storage: StorageProvider,
) -> bytes:
    """Read a previously stored report by URI, validating tenant ownership.

    Raises ForbiddenError if the URI doesn't belong to this org/pack.
    Raises NotFoundError if the report file doesn't exist in storage.
    """
    expected_prefix = f"{org_id}/{pack_id}/reports/"
    if not uri.startswith(expected_prefix):
        raise ForbiddenError("Report URI does not belong to this pack")
    try:
        return await storage.read(uri)
    except Exception:
        raise NotFoundError("Report")
