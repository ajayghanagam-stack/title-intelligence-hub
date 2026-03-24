"""Pipeline orchestrator for Title Search & Abstracting.

6-stage pipeline: order → retrieve → parse → chain → package → complete
Uses BackgroundTasks for MVP (Temporal support can be added later).

MVP Note: Parse, chain, and anomaly stages use deterministic mock functions
instead of AI agents (DocumentParserAgent, ChainBuilderAgent,
AnomalyDetectorAgent). When AI agents are wired in, they will be called from
this orchestrator via the service layer. The mock functions produce the same
output shape as the agents, so all downstream logic (flag rules, caching,
package generation) works identically. The agent classes and their tests exist
in ai/ and tests/title_search/test_*_agent.py respectively.
"""

import json
import uuid
import asyncio
import traceback
import logging
from datetime import datetime, timezone

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.micro_apps.title_search.models.order import TAOrder
from app.micro_apps.title_search.models.source_assignment import TASourceAssignment
from app.micro_apps.title_search.models.raw_document import TARawDocument
from app.micro_apps.title_search.models.document import TADocument
from app.micro_apps.title_search.models.chain_link import TAChainLink
from app.micro_apps.title_search.models.flag import TAFlag
from app.micro_apps.title_search.models.package import TAPackage
from app.micro_apps.title_search.models.pipeline_run import TAPipelineRun
from app.micro_apps.title_search.ai.source_resolver_agent import resolve_sources_for_order
from app.micro_apps.title_search.services.flag_rules import detect_all_flags, normalize_flags
from app.micro_apps.title_search.pipeline.version_tracker import (
    collect_version_info,
    compute_input_file_hash,
    compute_parse_cache_key,
    compute_parse_output_hash,
    compute_chain_cache_key,
)
from app.models.audit_event import AuditEvent

logger = logging.getLogger(__name__)

PIPELINE_STAGES = [
    ("order", 3),
    ("retrieve", 3),
    ("parse", 3),
    ("chain", 3),
    ("package", 3),
    ("complete", 3),
]

PIPELINE_TIMEOUT = 30 * 60  # 30 minutes


async def trigger_pipeline(
    order_id: uuid.UUID,
    org_id: uuid.UUID,
    session_factory: async_sessionmaker,
    background_tasks=None,
):
    if background_tasks:
        background_tasks.add_task(run_pipeline, order_id, org_id, session_factory)
    else:
        await run_pipeline(order_id, org_id, session_factory)


async def run_pipeline(
    order_id: uuid.UUID,
    org_id: uuid.UUID,
    session_factory: async_sessionmaker,
):
    try:
        await asyncio.wait_for(
            _run_pipeline_inner(order_id, org_id, session_factory),
            timeout=PIPELINE_TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.error(f"TSA pipeline timed out for order {order_id}")
        await _fail_order(session_factory, order_id, org_id, "Pipeline timed out")
    except Exception as e:
        logger.error(f"TSA pipeline error for order {order_id}: {e}\n{traceback.format_exc()}")
        await _fail_order(session_factory, order_id, org_id, str(e))


async def _fail_order(
    session_factory: async_sessionmaker,
    order_id: uuid.UUID,
    org_id: uuid.UUID,
    error: str,
):
    try:
        async with session_factory() as db:
            order = (await db.execute(
                select(TAOrder).where(TAOrder.id == order_id, TAOrder.org_id == org_id)
            )).scalar_one()
            order.status = "failed"
            order.pipeline_error = error
            await db.commit()
    except Exception as e:
        logger.error(f"Failed to mark order as failed: {e}")


STAGE_HANDLERS = {}


def _register_stage(name):
    def decorator(fn):
        STAGE_HANDLERS[name] = fn
        return fn
    return decorator


@_register_stage("order")
async def stage_order(order_id, org_id, db):
    """Validate order and resolve sources."""
    order = (await db.execute(
        select(TAOrder).where(TAOrder.id == order_id, TAOrder.org_id == org_id)
    )).scalar_one()

    await resolve_sources_for_order(db, org_id, order_id, order.county, order.state_code)


@_register_stage("retrieve")
async def stage_retrieve(order_id, org_id, db):
    """Mock retrieval — create sample raw documents for each source assignment.

    In production, this would use DocumentRetrievalAgent to navigate county portals.
    If any source is non_digital, the pipeline pauses (awaiting_abstractor).
    """
    assignments = (await db.execute(
        select(TASourceAssignment).where(
            TASourceAssignment.order_id == order_id,
            TASourceAssignment.org_id == org_id,
        )
    )).scalars().all()

    has_non_digital = any(a.availability == "non_digital" for a in assignments)

    for assignment in assignments:
        if assignment.availability == "non_digital" and assignment.status == "pending":
            # Non-digital source — skip retrieval, await ground abstractor upload
            continue

        # For digital/partial sources, create mock raw documents
        if assignment.status == "pending":
            raw_doc = TARawDocument(
                org_id=org_id,
                order_id=order_id,
                source_assignment_id=assignment.id,
                document_ref=f"MOCK-{assignment.source_type.upper()}-001",
                raw_content=_mock_raw_content(assignment.source_type),
                content_format="text",
            )
            db.add(raw_doc)
            assignment.status = "completed"

    # Check if any non-digital sources are still pending
    pending_non_digital = any(
        a.availability == "non_digital" and a.status == "pending"
        for a in assignments
    )
    if pending_non_digital:
        order = (await db.execute(
            select(TAOrder).where(TAOrder.id == order_id, TAOrder.org_id == org_id)
        )).scalar_one()
        order.status = "awaiting_abstractor"
        await db.commit()
        raise _PipelinePause("Awaiting ground abstractor upload")


@_register_stage("parse")
async def stage_parse(order_id, org_id, db):
    """Parse raw documents into structured documents.

    Caches output keyed by (raw document content hash + model + prompt + tool schema).
    On cache hit, replays cached documents without calling the parser.
    Idempotent: delete-then-insert.
    """
    from app.services.storage import get_storage

    raw_docs = (await db.execute(
        select(TARawDocument).where(
            TARawDocument.order_id == order_id,
            TARawDocument.org_id == org_id,
        )
    )).scalars().all()

    # Check parse cache
    settings = get_settings()
    version_info = collect_version_info(settings)
    storage = get_storage()
    input_hash = await compute_input_file_hash(storage, org_id, raw_docs)
    cache_key = compute_parse_cache_key(input_hash, version_info)
    cache_path = storage.make_ai_cache_path(org_id, order_id, "ta_parse", cache_key)

    if await storage.exists(cache_path):
        cached_docs = json.loads(await storage.read(cache_path))
        await _replay_parse_cache(db, org_id, order_id, cached_docs)
        logger.info(f"TSA parse cache hit — replayed {len(cached_docs)} documents for order {order_id}")
        return

    # Cache miss — run parser (mock for MVP)
    await db.execute(
        delete(TADocument).where(TADocument.order_id == order_id, TADocument.org_id == org_id)
    )

    for raw_doc in raw_docs:
        parsed = _mock_parse(raw_doc.raw_content or "", raw_doc.document_ref or "")
        doc = TADocument(
            org_id=org_id,
            order_id=order_id,
            raw_document_id=raw_doc.id,
            doc_type=parsed["doc_type"],
            recording_date=parsed.get("recording_date"),
            recording_ref=parsed.get("recording_ref"),
            grantor=parsed.get("grantor"),
            grantee=parsed.get("grantee"),
            consideration=parsed.get("consideration"),
            summary=parsed.get("summary"),
            confidence=parsed.get("confidence", 0.85),
            needs_review=parsed.get("confidence", 0.85) < 0.70,
        )
        db.add(doc)

    # Flush to get IDs, then serialize and cache
    await db.flush()
    docs = (await db.execute(
        select(TADocument).where(TADocument.order_id == order_id, TADocument.org_id == org_id)
    )).scalars().all()
    await storage.save(cache_path, _serialize_parse_output(docs))
    logger.info(f"TSA parse cache miss — cached {len(docs)} documents for order {order_id}")


@_register_stage("chain")
async def stage_chain(order_id, org_id, db):
    """Build chain of title and detect anomalies.

    Caches output keyed by (parse output hash + model + prompts + tools + rules version).
    On cache hit, replays cached chain links and flags without re-running logic.
    Idempotent: delete-then-insert.
    """
    from app.services.storage import get_storage

    documents = (await db.execute(
        select(TADocument).where(
            TADocument.order_id == order_id,
            TADocument.org_id == org_id,
        ).order_by(TADocument.recording_date)
    )).scalars().all()

    # Compute chain cache key from parse output
    settings = get_settings()
    version_info = collect_version_info(settings)
    storage = get_storage()

    docs_dicts = [
        {
            "doc_type": d.doc_type,
            "recording_date": d.recording_date,
            "recording_ref": d.recording_ref,
            "grantor": d.grantor,
            "grantee": d.grantee,
            "consideration": float(d.consideration) if d.consideration else None,
            "confidence": d.confidence,
        }
        for d in documents
    ]
    parse_output_hash = compute_parse_output_hash(docs_dicts)
    cache_key = compute_chain_cache_key(parse_output_hash, version_info)
    cache_path = storage.make_ai_cache_path(org_id, order_id, "ta_chain", cache_key)

    if await storage.exists(cache_path):
        cached_data = json.loads(await storage.read(cache_path))
        await _replay_chain_cache(db, org_id, order_id, cached_data)
        n_links = len(cached_data.get("chain_links", []))
        n_flags = len(cached_data.get("flags", []))
        logger.info(f"TSA chain cache hit — replayed {n_links} links, {n_flags} flags for order {order_id}")
        return

    # Cache miss — run chain building + anomaly detection
    await db.execute(
        delete(TAChainLink).where(TAChainLink.order_id == order_id, TAChainLink.org_id == org_id)
    )
    await db.execute(
        delete(TAFlag).where(TAFlag.order_id == order_id, TAFlag.org_id == org_id)
    )

    # Build chain links from parsed documents
    position = 1
    for doc in documents:
        if doc.doc_type in ("deed", "assignment"):
            link = TAChainLink(
                org_id=org_id,
                order_id=order_id,
                document_id=doc.id,
                position=position,
                link_type="conveyance",
                from_party=doc.grantor,
                to_party=doc.grantee,
                effective_date=doc.recording_date,
                is_gap=False,
            )
            db.add(link)
            position += 1
        elif doc.doc_type in ("mortgage", "lien", "easement"):
            link = TAChainLink(
                org_id=org_id,
                order_id=order_id,
                document_id=doc.id,
                position=position,
                link_type="encumbrance",
                from_party=doc.grantor,
                to_party=doc.grantee,
                effective_date=doc.recording_date,
                is_gap=False,
            )
            db.add(link)
            position += 1

    # Deterministic flag detection via rules engine
    raw_flags = detect_all_flags(documents)
    for rf in raw_flags:
        flag = TAFlag(
            org_id=org_id,
            order_id=order_id,
            document_id=rf.get("document_id"),
            flag_type=rf["flag_type"],
            severity=rf["severity"],
            title=rf["title"],
            description=rf["description"],
            evidence_refs=rf.get("evidence_refs", []),
        )
        db.add(flag)

    # Flush and cache results
    await db.flush()
    chain_links = (await db.execute(
        select(TAChainLink).where(TAChainLink.order_id == order_id, TAChainLink.org_id == org_id)
    )).scalars().all()
    flags = (await db.execute(
        select(TAFlag).where(TAFlag.order_id == order_id, TAFlag.org_id == org_id)
    )).scalars().all()
    await storage.save(cache_path, _serialize_chain_output(chain_links, flags))
    logger.info(f"TSA chain cache miss — cached {len(chain_links)} links, {len(flags)} flags for order {order_id}")


@_register_stage("package")
async def stage_package(order_id, org_id, db):
    """Auto-generate package if conditions met (idempotent: delete-then-insert)."""
    # Delete existing package for idempotent retry
    await db.execute(
        delete(TAPackage).where(TAPackage.order_id == order_id, TAPackage.org_id == org_id)
    )

    # Check if chain is complete (no gaps)
    chain_links = (await db.execute(
        select(TAChainLink).where(
            TAChainLink.order_id == order_id,
            TAChainLink.org_id == org_id,
        )
    )).scalars().all()

    chain_complete = len(chain_links) > 0 and not any(cl.is_gap for cl in chain_links)

    # Count open flags
    flags = (await db.execute(
        select(TAFlag).where(
            TAFlag.order_id == order_id,
            TAFlag.org_id == org_id,
            TAFlag.status == "open",
        )
    )).scalars().all()

    open_critical_high = sum(
        1 for f in flags if f.severity in ("critical", "high")
    )

    documents = (await db.execute(
        select(TADocument).where(
            TADocument.order_id == order_id,
            TADocument.org_id == org_id,
        )
    )).scalars().all()

    order = (await db.execute(
        select(TAOrder).where(TAOrder.id == order_id, TAOrder.org_id == org_id)
    )).scalar_one()

    # Generate package number
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y%m%d")
    existing_count = (await db.execute(
        select(TAPackage).where(
            TAPackage.org_id == org_id,
            TAPackage.package_number.like(f"TA-{date_str}-%"),
        )
    )).scalars().all()
    seq = len(existing_count) + 1
    package_number = f"TA-{date_str}-{seq:04d}"

    # Check if auto-issue conditions are met
    can_auto_issue = chain_complete and open_critical_high == 0

    pkg = TAPackage(
        org_id=org_id,
        order_id=order_id,
        package_number=package_number,
        status="issued" if can_auto_issue else "draft",
        search_scope=order.search_scope,
        years_covered=order.search_years,
        total_documents=len(documents),
        chain_complete=chain_complete,
        open_flags_count=len(flags),
        property_summary={
            "address": order.property_address,
            "county": order.county,
            "state": order.state_code,
            "parcel_number": order.parcel_number,
        },
        issued_by="auto" if can_auto_issue else None,
        issued_at=now if can_auto_issue else None,
    )
    db.add(pkg)


@_register_stage("complete")
async def stage_complete(order_id, org_id, db):
    """Final stage — set order status."""
    order = (await db.execute(
        select(TAOrder).where(TAOrder.id == order_id, TAOrder.org_id == org_id)
    )).scalar_one()

    # Check for unresolved flags
    flags = (await db.execute(
        select(TAFlag).where(
            TAFlag.order_id == order_id,
            TAFlag.org_id == org_id,
            TAFlag.status == "open",
        )
    )).scalars().all()

    critical_high = [f for f in flags if f.severity in ("critical", "high")]
    if critical_high:
        order.status = "review_required"
    else:
        order.status = "completed"

    order.pipeline_stage = None


class _PipelinePause(Exception):
    """Raised when pipeline should pause (e.g., awaiting ground abstractor)."""
    pass


async def _run_pipeline_inner(
    order_id: uuid.UUID,
    org_id: uuid.UUID,
    session_factory: async_sessionmaker,
):
    # Create a pipeline run record with version metadata
    settings = get_settings()
    version_info = collect_version_info(settings)
    pipeline_run_id: uuid.UUID | None = None

    async with session_factory() as db:
        run = TAPipelineRun(
            org_id=org_id,
            order_id=order_id,
            ai_platform=version_info["ai_platform"],
            ai_model=version_info["ai_model"],
            parser_prompt_hash=version_info["parser_prompt_hash"],
            chain_prompt_hash=version_info["chain_prompt_hash"],
            anomaly_prompt_hash=version_info["anomaly_prompt_hash"],
            parser_tool_hash=version_info["parser_tool_hash"],
            chain_tool_hash=version_info["chain_tool_hash"],
            anomaly_tool_hash=version_info["anomaly_tool_hash"],
            rules_version=version_info["rules_version"],
            pipeline_backend=version_info["pipeline_backend"],
            version_metadata=version_info["version_metadata"],
            status="running",
        )
        db.add(run)
        await db.commit()
        await db.refresh(run)
        pipeline_run_id = run.id

    for stage_name, max_retries in PIPELINE_STAGES:
        logger.info(f"TSA pipeline stage '{stage_name}' starting for order {order_id}")

        async with session_factory() as db:
            order = (await db.execute(
                select(TAOrder).where(TAOrder.id == order_id, TAOrder.org_id == org_id)
            )).scalar_one()
            order.pipeline_stage = stage_name
            order.status = "processing"
            await db.commit()

        handler = STAGE_HANDLERS[stage_name]
        success = False
        last_error = None

        for attempt in range(max_retries):
            try:
                async with session_factory() as db:
                    await handler(order_id, org_id, db)
                    await db.commit()
                success = True
                logger.info(f"TSA stage '{stage_name}' completed for order {order_id}")
                break
            except _PipelinePause:
                logger.info(f"TSA pipeline paused at '{stage_name}' for order {order_id}")
                return
            except Exception as e:
                last_error = e
                logger.warning(
                    f"TSA stage '{stage_name}' attempt {attempt + 1}/{max_retries} failed: {e}"
                )
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)

        if not success:
            async with session_factory() as db:
                order = (await db.execute(
                    select(TAOrder).where(TAOrder.id == order_id, TAOrder.org_id == org_id)
                )).scalar_one()
                order.status = "failed"
                order.pipeline_error = f"Failed at stage '{stage_name}': {last_error}"
                if pipeline_run_id:
                    run = (await db.execute(
                        select(TAPipelineRun).where(
                            TAPipelineRun.id == pipeline_run_id,
                            TAPipelineRun.org_id == org_id,
                        )
                    )).scalar_one_or_none()
                    if run:
                        run.status = "failed"
                        run.error_message = f"Failed at stage '{stage_name}': {last_error}"
                        run.completed_at = datetime.now(timezone.utc)
                db.add(AuditEvent(
                    org_id=org_id,
                    action="ta_pipeline_failed",
                    target_type="ta_order",
                    target_id=order_id,
                    metadata_={"stage": stage_name, "error": str(last_error)},
                ))
                await db.commit()
            return

    # All stages completed — mark pipeline run as completed
    async with session_factory() as db:
        if pipeline_run_id:
            run = (await db.execute(
                select(TAPipelineRun).where(
                    TAPipelineRun.id == pipeline_run_id,
                    TAPipelineRun.org_id == org_id,
                )
            )).scalar_one_or_none()
            if run:
                run.status = "completed"
                run.completed_at = datetime.now(timezone.utc)

                # Compute confidence summary from parsed documents
                docs = (await db.execute(
                    select(TADocument).where(
                        TADocument.order_id == order_id,
                        TADocument.org_id == org_id,
                    )
                )).scalars().all()
                confidences = [d.confidence for d in docs if d.confidence is not None]
                if confidences:
                    run.confidence_summary = {
                        "doc_count": len(docs),
                        "scored_count": len(confidences),
                        "min": round(min(confidences), 4),
                        "max": round(max(confidences), 4),
                        "mean": round(sum(confidences) / len(confidences), 4),
                        "below_threshold": sum(
                            1 for c in confidences if c < 0.70
                        ),
                    }
                else:
                    run.confidence_summary = {
                        "doc_count": len(docs),
                        "scored_count": 0,
                    }
        db.add(AuditEvent(
            org_id=org_id,
            action="ta_pipeline_completed",
            target_type="ta_order",
            target_id=order_id,
        ))
        await db.commit()

    logger.info(f"TSA pipeline completed for order {order_id}")


def _mock_raw_content(source_type: str) -> str:
    """Generate mock raw document content for testing."""
    if source_type == "recorder":
        return (
            "WARRANTY DEED\n"
            "Recording Date: 2020-01-15\n"
            "Recording Reference: 2020-001234\n"
            "Grantor: John Smith\n"
            "Grantee: Jane Doe\n"
            "Consideration: $250,000.00\n"
            "Legal Description: Lot 1, Block 2, Sample Subdivision"
        )
    elif source_type == "clerk":
        return (
            "MORTGAGE\n"
            "Recording Date: 2020-02-01\n"
            "Recording Reference: 2020-001235\n"
            "Mortgagor: Jane Doe\n"
            "Mortgagee: First National Bank\n"
            "Amount: $200,000.00"
        )
    else:
        return (
            "PROPERTY TAX RECORD\n"
            "Parcel: 12-34-567-890\n"
            "Owner: Jane Doe\n"
            "Assessed Value: $225,000.00"
        )


def _mock_parse(raw_content: str, document_ref: str) -> dict:
    """Simple mock parser for pipeline testing."""
    content_lower = raw_content.lower()

    if "warranty deed" in content_lower or "deed" in content_lower:
        return {
            "doc_type": "deed",
            "recording_date": "2020-01-15",
            "recording_ref": document_ref or "2020-001234",
            "grantor": {"names": ["John Smith"], "entity_type": "individual"},
            "grantee": {"names": ["Jane Doe"], "entity_type": "individual"},
            "consideration": 250000.00,
            "summary": "Warranty deed transferring property",
            "confidence": 0.92,
        }
    elif "mortgage" in content_lower:
        return {
            "doc_type": "mortgage",
            "recording_date": "2020-02-01",
            "recording_ref": document_ref or "2020-001235",
            "grantor": {"names": ["Jane Doe"], "entity_type": "individual"},
            "grantee": {"names": ["First National Bank"], "entity_type": "corporation"},
            "consideration": 200000.00,
            "summary": "Mortgage on property",
            "confidence": 0.88,
        }
    else:
        return {
            "doc_type": "other",
            "recording_ref": document_ref,
            "summary": "Property record",
            "confidence": 0.75,
        }


# ---------------------------------------------------------------------------
# Cache serialization / replay helpers
# ---------------------------------------------------------------------------

def _serialize_parse_output(documents: list) -> bytes:
    """Serialize TADocument ORM objects to JSON for caching."""
    docs_dicts = [
        {
            "doc_type": d.doc_type,
            "recording_date": d.recording_date,
            "recording_ref": d.recording_ref,
            "grantor": d.grantor,
            "grantee": d.grantee,
            "consideration": float(d.consideration) if d.consideration else None,
            "summary": d.summary,
            "confidence": d.confidence,
            "needs_review": d.needs_review,
            "raw_document_id": str(d.raw_document_id) if d.raw_document_id else None,
        }
        for d in documents
    ]
    return json.dumps(docs_dicts, sort_keys=True).encode("utf-8")


async def _replay_parse_cache(
    db: AsyncSession, org_id: uuid.UUID, order_id: uuid.UUID, cached_docs: list[dict],
) -> None:
    """Insert documents from cached JSON into the database."""
    await db.execute(
        delete(TADocument).where(TADocument.order_id == order_id, TADocument.org_id == org_id)
    )
    for d in cached_docs:
        raw_doc_id = d.get("raw_document_id")
        db.add(TADocument(
            org_id=org_id,
            order_id=order_id,
            raw_document_id=uuid.UUID(raw_doc_id) if raw_doc_id else None,
            doc_type=d["doc_type"],
            recording_date=d.get("recording_date"),
            recording_ref=d.get("recording_ref"),
            grantor=d.get("grantor"),
            grantee=d.get("grantee"),
            consideration=d.get("consideration"),
            summary=d.get("summary"),
            confidence=d.get("confidence", 0.85),
            needs_review=d.get("needs_review", False),
        ))


def _serialize_chain_output(chain_links: list, flags: list) -> bytes:
    """Serialize TAChainLink and TAFlag ORM objects to JSON for caching."""
    links_dicts = [
        {
            "position": cl.position,
            "link_type": cl.link_type,
            "document_id": str(cl.document_id) if cl.document_id else None,
            "from_party": cl.from_party,
            "to_party": cl.to_party,
            "effective_date": cl.effective_date,
            "is_gap": cl.is_gap,
            "gap_description": cl.gap_description,
        }
        for cl in chain_links
    ]
    flags_dicts = [
        {
            "flag_type": f.flag_type,
            "severity": f.severity,
            "title": f.title,
            "description": f.description,
            "ai_explanation": f.ai_explanation,
            "evidence_refs": f.evidence_refs or [],
            "document_id": str(f.document_id) if f.document_id else None,
            "chain_link_id": str(f.chain_link_id) if f.chain_link_id else None,
            "status": f.status,
        }
        for f in flags
    ]
    return json.dumps({"chain_links": links_dicts, "flags": flags_dicts}, sort_keys=True).encode("utf-8")


async def _replay_chain_cache(
    db: AsyncSession, org_id: uuid.UUID, order_id: uuid.UUID, cached_data: dict,
) -> None:
    """Insert chain links and flags from cached JSON into the database."""
    await db.execute(
        delete(TAChainLink).where(TAChainLink.order_id == order_id, TAChainLink.org_id == org_id)
    )
    await db.execute(
        delete(TAFlag).where(TAFlag.order_id == order_id, TAFlag.org_id == org_id)
    )
    for cl in cached_data["chain_links"]:
        doc_id = cl.get("document_id")
        db.add(TAChainLink(
            org_id=org_id,
            order_id=order_id,
            document_id=uuid.UUID(doc_id) if doc_id else None,
            position=cl["position"],
            link_type=cl["link_type"],
            from_party=cl.get("from_party"),
            to_party=cl.get("to_party"),
            effective_date=cl.get("effective_date"),
            is_gap=cl.get("is_gap", False),
            gap_description=cl.get("gap_description"),
        ))
    for f in cached_data["flags"]:
        doc_id = f.get("document_id")
        cl_id = f.get("chain_link_id")
        db.add(TAFlag(
            org_id=org_id,
            order_id=order_id,
            document_id=uuid.UUID(doc_id) if doc_id else None,
            chain_link_id=uuid.UUID(cl_id) if cl_id else None,
            flag_type=f["flag_type"],
            severity=f["severity"],
            title=f["title"],
            description=f["description"],
            ai_explanation=f.get("ai_explanation"),
            evidence_refs=f.get("evidence_refs", []),
            status=f.get("status", "open"),
        ))
