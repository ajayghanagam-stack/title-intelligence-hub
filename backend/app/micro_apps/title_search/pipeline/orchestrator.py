"""Pipeline orchestrator for Title Search & Abstracting.

6-stage pipeline: order → retrieve → parse → chain → package → complete
Uses BackgroundTasks (Temporal support can be added later).

AI agents (DocumentParserAgent, ChainAnalysisAgent) are called from this
orchestrator. Deterministic flag rules (detect_all_flags) run alongside
AI anomaly detection; results are merged via normalize_flags.
"""

import json
import time
import uuid
import asyncio
import traceback
import logging
from dataclasses import dataclass
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
from app.micro_apps.title_search.models.county_source import TACountySource
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
    ("retrieve", 3),  # race-based fetch with per-stage timeout
    ("parse", 3),
    ("chain", 3),
    ("package", 3),
    ("complete", 3),
]

PIPELINE_TIMEOUT = 30 * 60  # 30 minutes
STAGE_TIMEOUT = 5 * 60  # 5 minutes per stage
DISCOVERY_TIMEOUT = 60  # 60 seconds for AI portal discovery


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
    """Validate order and geocode address to identify county."""
    from app.micro_apps.title_search.services.geocoding import geocode_address

    order = (await db.execute(
        select(TAOrder).where(TAOrder.id == order_id, TAOrder.org_id == org_id)
    )).scalar_one()

    # Build address for geocoding
    address_parts = [order.property_address]
    if order.city:
        address_parts.append(order.city)
    if order.state_code:
        address_parts.append(order.state_code)
    if order.zip_code:
        address_parts.append(order.zip_code)
    full_address = ", ".join(address_parts)

    # Geocode to fill county if missing
    if not order.county:
        geo = await geocode_address(full_address)
        if geo:
            order.county = geo["county"]
            if not order.state_code:
                order.state_code = geo["state_code"]
            logger.info(f"Geocoded address → {order.county} County, {order.state_code}")
        else:
            logger.warning(f"Geocoding failed for: {full_address}")

    order.status = "processing"


@_register_stage("retrieve")
async def stage_retrieve(order_id, org_id, db):
    """Fetch property data from real county portals.

    Uses API-first approach (Census geocoder, ArcGIS) with
    Playwright scraping fallback for tax collectors and clerk portals.
    CAPTCHA-blocked portals are flagged for manual retrieval.
    """
    from app.micro_apps.title_search.services.geocoding import geocode_address
    from app.micro_apps.title_search.services.real_data_fetcher import fetch_property_data

    order = (await db.execute(
        select(TAOrder).where(TAOrder.id == order_id, TAOrder.org_id == org_id)
    )).scalar_one()

    # Build full address for geocoding
    address_parts = [order.property_address]
    if order.city:
        address_parts.append(order.city)
    if order.state_code:
        address_parts.append(order.state_code)
    if order.zip_code:
        address_parts.append(order.zip_code)
    full_address = ", ".join(address_parts)

    # Geocode if county not already set
    if not order.county or not order.state_code:
        geo = await geocode_address(full_address)
        if not geo:
            raise RuntimeError(
                f"Could not geocode address: {full_address}. "
                "Please verify the address is correct."
            )
        order.county = geo["county"]
        order.state_code = geo["state_code"]
        if geo.get("matched_address"):
            logger.info(f"Geocoded '{full_address}' → {geo['county']} County, {geo['state_code']}")

    # Fetch real property data from available portals
    search_address = order.property_address
    # Use just the street portion for tax collector search
    if "," in search_address:
        search_address = search_address.split(",")[0].strip()

    prop_data = await fetch_property_data(
        address=search_address,
        county=order.county,
        state_code=order.state_code,
        owner_name=order.borrower_name or "",
        search_scope=order.search_scope or "full",
    )

    # Update order with fetched data
    if prop_data.owner_name and not order.borrower_name:
        order.borrower_name = prop_data.owner_name
    if prop_data.parcel_number and not order.parcel_number:
        order.parcel_number = prop_data.parcel_number
    if prop_data.legal_description and not order.legal_description:
        order.legal_description = prop_data.legal_description

    # Store the fetched data as a raw document (JSON format)
    import dataclasses
    raw_content = json.dumps(dataclasses.asdict(prop_data), default=str, indent=2)

    raw_doc = TARawDocument(
        org_id=org_id,
        order_id=order_id,
        document_ref=f"{order.county.upper()}-PROPERTY-DATA",
        raw_content=raw_content,
        content_format="json",
        source_url=", ".join(
            s.get("url", "") for s in prop_data.sources_used if s.get("url")
        ),
    )
    db.add(raw_doc)

    # Create source assignments for tracking
    for source in prop_data.sources_used:
        assignment = TASourceAssignment(
            org_id=org_id,
            order_id=order_id,
            source_type=source.get("type", "unknown"),
            availability="digital",
            status="completed",
        )
        db.add(assignment)

    for source in prop_data.sources_failed:
        assignment = TASourceAssignment(
            org_id=org_id,
            order_id=order_id,
            source_type=source.get("type", "unknown"),
            availability="digital" if not source.get("manual_retrieval") else "non_digital",
            status="failed",
        )
        db.add(assignment)

        # Create a flag for CAPTCHA-blocked portals
        if source.get("captcha_blocked"):
            captcha_flag = TAFlag(
                org_id=org_id,
                order_id=order_id,
                title=f"Clerk Portal CAPTCHA Blocked ({source.get('type', 'unknown')})",
                description=(
                    f"Automated access to {source.get('url', 'clerk portal')} "
                    f"was blocked by CAPTCHA. Manual retrieval of clerk records "
                    f"is required. Error: {source.get('error', 'N/A')}"
                ),
                severity="medium",
                flag_type="captcha_blocked",
                status="open",
            )
            db.add(captcha_flag)

    # If no data was retrieved at all, fail
    if not prop_data.sources_used:
        errors = "; ".join(s.get("error", "Unknown") for s in prop_data.sources_failed)
        raise RuntimeError(
            f"Unable to retrieve any property data for {order.county} County, "
            f"{order.state_code}. Errors: {errors}"
        )


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

    # Cache miss — run AI parser
    await db.execute(
        delete(TADocument).where(TADocument.order_id == order_id, TADocument.org_id == org_id)
    )

    # Load order for context (address, search_scope)
    order = (await db.execute(
        select(TAOrder).where(TAOrder.id == order_id, TAOrder.org_id == org_id)
    )).scalar_one()

    for raw_doc in raw_docs:
        if raw_doc.content_format == "json":
            # Structured JSON from real data fetcher
            await _parse_json_property_data(db, org_id, order_id, raw_doc, order)
        elif raw_doc.content_format == "html":
            # HTML from county portal — use PropertyDataExtractorAgent
            await _parse_html_document(db, org_id, order_id, raw_doc, order)
        else:
            # Plain text — use existing DocumentParserAgent (backward compat)
            await _parse_text_document(db, org_id, order_id, raw_doc)

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

    # Cache miss — run combined AI chain analysis
    from app.micro_apps.title_search.ai.chain_analysis_agent import ChainAnalysisAgent

    await db.execute(
        delete(TAChainLink).where(TAChainLink.order_id == order_id, TAChainLink.org_id == org_id)
    )
    await db.execute(
        delete(TAFlag).where(TAFlag.order_id == order_id, TAFlag.org_id == org_id)
    )

    # Build chain of title + detect anomalies in a single LLM call
    docs_for_chain = [
        {
            "id": str(d.id),
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

    analysis_agent = ChainAnalysisAgent(org_id)
    analysis_result = await analysis_agent.analyze(docs_for_chain)

    # Insert chain links from AI result
    for cl in analysis_result.get("chain_links", []):
        doc_id = cl.get("document_id")
        if doc_id and not isinstance(doc_id, uuid.UUID):
            try:
                doc_id = uuid.UUID(doc_id)
            except (ValueError, AttributeError):
                doc_id = None
        link = TAChainLink(
            org_id=org_id,
            order_id=order_id,
            document_id=doc_id or None,
            position=cl.get("position", 0),
            link_type=cl.get("link_type", "conveyance"),
            from_party=cl.get("from_party"),
            to_party=cl.get("to_party"),
            effective_date=cl.get("effective_date"),
            is_gap=cl.get("is_gap", False),
            gap_description=cl.get("gap_description"),
        )
        db.add(link)

    # AI anomalies + deterministic rules — merge results
    ai_flags = analysis_result.get("anomalies", [])
    rule_flags = detect_all_flags(documents)
    all_flags = normalize_flags(ai_flags + rule_flags)

    for rf in all_flags:
        _doc_id = rf.get("document_id")
        if _doc_id and not isinstance(_doc_id, uuid.UUID):
            try:
                _doc_id = uuid.UUID(_doc_id)
            except (ValueError, AttributeError):
                _doc_id = None
        _cl_id = rf.get("chain_link_id")
        if _cl_id and not isinstance(_cl_id, uuid.UUID):
            try:
                _cl_id = uuid.UUID(_cl_id)
            except (ValueError, AttributeError):
                _cl_id = None
        flag = TAFlag(
            org_id=org_id,
            order_id=order_id,
            document_id=_doc_id or None,
            chain_link_id=_cl_id or None,
            flag_type=rf["flag_type"],
            severity=rf["severity"],
            title=rf["title"],
            description=rf["description"],
            ai_explanation=rf.get("ai_explanation"),
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

    property_summary = {
        "address": order.property_address,
        "county": order.county,
        "state": order.state_code,
        "parcel_number": order.parcel_number,
    }

    # Generate data-driven narrative (no LLM call)
    narrative = _generate_data_driven_narrative(
        order=order,
        documents=documents,
        chain_links=chain_links,
        flags=flags,
        chain_complete=chain_complete,
    )
    property_summary["narrative"] = narrative

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
        property_summary=property_summary,
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


def _generate_data_driven_narrative(
    order, documents, chain_links, flags, chain_complete: bool,
) -> str:
    """Build a bullet-point narrative from structured data (no LLM call)."""
    address = order.property_address or "Unknown"
    county = order.county or "Unknown"
    state = order.state_code or "Unknown"
    scope = order.search_scope or "full"
    years = order.search_years or 30

    doc_types: dict[str, int] = {}
    for d in documents:
        dt = d.doc_type if hasattr(d, "doc_type") else d.get("doc_type", "other")
        doc_types[dt] = doc_types.get(dt, 0) + 1

    type_parts = []
    for dt in ("deed", "mortgage", "lien", "easement", "satisfaction", "other"):
        count = doc_types.get(dt, 0)
        if count:
            type_parts.append(f"{count} {dt}{'s' if count != 1 else ''}")

    sev_counts: dict[str, int] = {}
    for f in flags:
        sev = f.severity if hasattr(f, "severity") else f.get("severity", "low")
        sev_counts[sev] = sev_counts.get(sev, 0) + 1

    chain_status = "complete" if chain_complete else "incomplete — gaps detected"

    lines = [
        f"Title search for {address}, {county} County, {state}.",
        f"{scope.capitalize()} search covering {years} years.",
        f"{len(documents)} documents found: {', '.join(type_parts) if type_parts else 'none'}.",
        f"Chain of title: {len(chain_links)} links, {chain_status}.",
    ]

    if flags:
        flag_parts = []
        for sev in ("critical", "high", "medium", "low"):
            cnt = sev_counts.get(sev, 0)
            if cnt:
                flag_parts.append(f"{cnt} {sev}")
        lines.append(f"{len(flags)} flags: {', '.join(flag_parts)}.")
    else:
        lines.append("No flags detected.")

    return "\n".join(lines)


@dataclass
class _RaceResult:
    """Result from the portal race."""
    fetch_result: object  # FetchResult
    assignment: object | None = None  # TASourceAssignment if registered portal won
    county_source: object | None = None  # TACountySource if registered portal won
    portal_info: dict | None = None  # if discovered portal won


# Sentinel to tag tasks so we know what they represent
_DISCOVERY_TAG = "_discovery_"


async def _race_fetch(
    fetcher,
    fetchable: list[tuple],
    order: TAOrder,
    org_id: uuid.UUID,
) -> tuple["_RaceResult | None", list[str]]:
    """Race registered portals against AI discovery — first success wins.

    Fires all registered portal fetches and AI discovery concurrently.
    When discovery completes, spawns fetch tasks for discovered URLs.
    First successful fetch cancels all remaining tasks.

    Returns (winner_result_or_None, error_list).
    """
    from app.micro_apps.title_search.ai.portal_discovery_agent import PortalDiscoveryAgent
    from app.micro_apps.title_search.services.county_data_fetcher import FetchResult
    from urllib.parse import quote_plus

    errors: list[str] = []
    pending: set[asyncio.Task] = set()
    # Map task → metadata for identifying winners
    task_meta: dict[asyncio.Task, dict] = {}

    # --- Helper: create a fetch task for a registered portal ---
    async def _fetch_registered(assignment, county_source):
        return await fetcher.fetch(
            county_source=county_source,
            address=order.property_address,
            parcel=order.parcel_number,
        )

    # --- Helper: create a fetch task for a discovered URL (with DNS check) ---
    async def _fetch_discovered(url: str):
        import socket
        from urllib.parse import urlparse
        from app.micro_apps.title_search.services.county_data_fetcher import FetchResult
        # Quick DNS check to reject hallucinated domains before wasting 30s on connect
        try:
            hostname = urlparse(url).hostname
            if hostname:
                await asyncio.get_event_loop().run_in_executor(
                    None, socket.getaddrinfo, hostname, None,
                )
        except socket.gaierror:
            return FetchResult(
                success=False,
                error=f"Domain does not exist: {hostname}",
                source_url=url,
            )
        return await fetcher.fetch_url(url)

    # --- Helper: run AI discovery (with timeout) ---
    async def _run_discovery():
        agent = PortalDiscoveryAgent(org_id)
        return await asyncio.wait_for(
            agent.discover(order.county, order.state_code),
            timeout=DISCOVERY_TIMEOUT,
        )

    # Phase 1: Launch registered portal fetch tasks
    for assignment, county_source in fetchable:
        task = asyncio.create_task(
            _fetch_registered(assignment, county_source),
            name=f"fetch-{county_source.portal_url}",
        )
        pending.add(task)
        task_meta[task] = {
            "type": "registered",
            "assignment": assignment,
            "county_source": county_source,
        }

    # Phase 2: Launch AI discovery task concurrently
    discovery_task = asyncio.create_task(
        _run_discovery(), name="discovery",
    )
    pending.add(discovery_task)
    task_meta[discovery_task] = {"type": _DISCOVERY_TAG}

    # If no fetchable portals and no discovery, bail early
    if not pending:
        return None, ["No portal sources available"]

    winner: _RaceResult | None = None

    try:
        while pending and winner is None:
            done, pending = await asyncio.wait(
                pending, return_when=asyncio.FIRST_COMPLETED,
            )

            for task in done:
                meta = task_meta.pop(task, {})
                exc = task.exception() if not task.cancelled() else None

                if meta.get("type") == _DISCOVERY_TAG:
                    # Discovery finished — spawn fetch tasks for any portals found
                    if exc:
                        logger.warning(f"Portal discovery failed: {exc}")
                        errors.append(f"AI discovery error: {exc}")
                        continue

                    discovery = task.result()
                    portals = discovery.get("portals", [])
                    if not portals:
                        has_digital = discovery.get("county_has_digital_records", True)
                        if not has_digital:
                            errors.append(
                                f"{order.county} County, {order.state_code} does not "
                                "appear to have digitized records online"
                            )
                        else:
                            errors.append(
                                f"AI found no portals for "
                                f"{order.county} County, {order.state_code}"
                            )
                        continue

                    # Spawn parallel fetch tasks for discovered URLs
                    for portal_info in portals:
                        url_template = portal_info.get("url", "")
                        if not url_template:
                            continue
                        url = url_template.replace(
                            "{address}", quote_plus(order.property_address),
                        )
                        url = url.replace(
                            "{parcel}", quote_plus(order.parcel_number or ""),
                        )
                        dtask = asyncio.create_task(
                            _fetch_discovered(url),
                            name=f"fetch-discovered-{url[:60]}",
                        )
                        pending.add(dtask)
                        task_meta[dtask] = {
                            "type": "discovered",
                            "portal_info": portal_info,
                            "url": url,
                        }
                    continue

                # It's a fetch task (registered or discovered)
                if exc:
                    label = meta.get("county_source")
                    portal_url = getattr(label, "portal_url", None) or meta.get("url", "unknown")
                    err = f"{portal_url}: {exc}"
                    logger.warning(f"Fetch task exception: {err}")
                    errors.append(err)
                    if meta.get("type") == "registered" and meta.get("assignment"):
                        meta["assignment"].status = "failed"
                    continue

                result: FetchResult = task.result()
                if result.success:
                    if meta.get("type") == "registered":
                        winner = _RaceResult(
                            fetch_result=result,
                            assignment=meta["assignment"],
                            county_source=meta["county_source"],
                        )
                    else:
                        winner = _RaceResult(
                            fetch_result=result,
                            portal_info=meta.get("portal_info"),
                        )
                    logger.info(
                        f"Race winner ({meta.get('type')}): "
                        f"{result.source_url} in {result.elapsed_seconds}s"
                    )
                    break
                else:
                    portal_url = (
                        getattr(meta.get("county_source"), "portal_url", None)
                        or meta.get("url", "unknown")
                    )
                    err = f"{portal_url}: {result.error}"
                    logger.warning(f"Fetch failed: {err}")
                    errors.append(err)
                    if meta.get("type") == "registered" and meta.get("assignment"):
                        meta["assignment"].status = "failed"
    finally:
        # Cancel all remaining tasks
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        # Clean up metadata for cancelled tasks
        for task in pending:
            task_meta.pop(task, None)

    return winner, errors


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

    pipeline_start = time.monotonic()
    stage_timings: dict[str, float] = {}

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
        stage_start = time.monotonic()

        for attempt in range(max_retries):
            try:
                async with session_factory() as db:
                    await asyncio.wait_for(
                        handler(order_id, org_id, db),
                        timeout=STAGE_TIMEOUT,
                    )
                    await db.commit()
                success = True
                stage_timings[stage_name] = round(time.monotonic() - stage_start, 3)
                logger.info(
                    f"TSA stage '{stage_name}' completed for order {order_id} "
                    f"in {stage_timings[stage_name]}s"
                )
                break
            except _PipelinePause:
                stage_timings[stage_name] = round(time.monotonic() - stage_start, 3)
                logger.info(f"TSA pipeline paused at '{stage_name}' for order {order_id}")
                # Mark pipeline run as paused so frontend doesn't show infinite spinner
                if pipeline_run_id:
                    async with session_factory() as db:
                        run = (await db.execute(
                            select(TAPipelineRun).where(
                                TAPipelineRun.id == pipeline_run_id,
                                TAPipelineRun.org_id == org_id,
                            )
                        )).scalar_one_or_none()
                        if run:
                            run.status = "paused"
                            meta = run.version_metadata or {}
                            meta["stage_timings"] = stage_timings
                            meta["paused_at_stage"] = stage_name
                            run.version_metadata = meta
                        await db.commit()
                return
            except asyncio.TimeoutError:
                elapsed = round(time.monotonic() - stage_start, 3)
                last_error = RuntimeError(
                    f"Stage '{stage_name}' timed out after {STAGE_TIMEOUT}s "
                    f"(elapsed {elapsed}s)"
                )
                logger.error(
                    f"TSA stage '{stage_name}' timed out for order {order_id} "
                    f"(attempt {attempt + 1}/{max_retries}, {elapsed}s)"
                )
                # Don't retry on timeout — it will just timeout again
                break
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
    total_elapsed = round(time.monotonic() - pipeline_start, 3)
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

                # Save stage timings in version_metadata
                meta = run.version_metadata or {}
                meta["stage_timings"] = stage_timings
                meta["total_elapsed_seconds"] = total_elapsed
                run.version_metadata = meta

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


async def _parse_html_document(
    db: AsyncSession, org_id: uuid.UUID, order_id: uuid.UUID,
    raw_doc: TARawDocument, order: TAOrder,
) -> None:
    """Parse HTML from county portal into multiple TADocuments using AI extractor."""
    from app.micro_apps.title_search.ai.property_data_extractor import PropertyDataExtractorAgent

    extractor = PropertyDataExtractorAgent(org_id)
    result = await extractor.extract_all(
        raw_content=raw_doc.raw_content or "",
        search_scope=order.search_scope or "full",
        property_address=order.property_address or "",
    )

    prop_info = result.get("property_info", {})
    confidence = result.get("confidence", 0.80)

    # Update order's legal_description from extracted data if blank
    if not order.legal_description and prop_info.get("legal_description"):
        order.legal_description = prop_info["legal_description"]

    # Create TADocuments for each deed
    for deed in result.get("deeds", []):
        doc = TADocument(
            org_id=org_id,
            order_id=order_id,
            raw_document_id=raw_doc.id,
            doc_type=deed.get("doc_type", "deed"),
            recording_date=deed.get("recording_date"),
            recording_ref=deed.get("instrument_number") or deed.get("recording_ref"),
            grantor={"names": [deed["grantor"]]} if deed.get("grantor") else None,
            grantee={"names": [deed["grantee"]]} if deed.get("grantee") else None,
            consideration=deed.get("consideration"),
            summary=deed.get("deed_type_detail"),
            confidence=confidence,
            needs_review=confidence < 0.70,
            doc_metadata={
                "book_page": deed.get("book_page"),
                "instrument_number": deed.get("instrument_number"),
                "deed_type_detail": deed.get("deed_type_detail"),
                "subdivision": prop_info.get("subdivision"),
            },
        )
        db.add(doc)

    # Create TADocuments for each mortgage
    for mtg in result.get("mortgages", []):
        doc = TADocument(
            org_id=org_id,
            order_id=order_id,
            raw_document_id=raw_doc.id,
            doc_type="mortgage",
            recording_date=mtg.get("recording_date"),
            recording_ref=mtg.get("instrument_number") or mtg.get("recording_ref"),
            grantor={"names": [mtg["lender"]]} if mtg.get("lender") else None,
            grantee={"names": [mtg["borrower"]]} if mtg.get("borrower") else None,
            consideration=mtg.get("loan_amount"),
            confidence=confidence,
            needs_review=confidence < 0.70,
            doc_metadata={
                "book_page": mtg.get("book_page"),
                "instrument_number": mtg.get("instrument_number"),
                "trustee": mtg.get("trustee"),
                "maturity_date": mtg.get("maturity_date"),
                "open_closed_end": mtg.get("open_closed_end"),
                "min_number": mtg.get("min_number"),
                "riders": mtg.get("riders"),
                "associated_docs": mtg.get("associated_docs"),
                "comments": mtg.get("comments"),
            },
        )
        db.add(doc)

    # Create TADocuments for each lien
    for lien in result.get("liens", []):
        doc = TADocument(
            org_id=org_id,
            order_id=order_id,
            raw_document_id=raw_doc.id,
            doc_type="lien",
            recording_date=lien.get("recording_date"),
            recording_ref=lien.get("instrument_number") or lien.get("recording_ref"),
            grantor={"names": [lien["creditor"]]} if lien.get("creditor") else None,
            grantee={"names": [lien["debtor"]]} if lien.get("debtor") else None,
            consideration=lien.get("amount"),
            summary=lien.get("lien_type"),
            confidence=confidence,
            needs_review=confidence < 0.70,
            doc_metadata={
                "book_page": lien.get("book_page"),
                "instrument_number": lien.get("instrument_number"),
                "lien_status": lien.get("status"),
            },
        )
        db.add(doc)

    # Store tax info in doc_metadata on a special "other" document
    tax_info = result.get("tax_info")
    if tax_info and any(v for v in tax_info.values() if v is not None):
        doc = TADocument(
            org_id=org_id,
            order_id=order_id,
            raw_document_id=raw_doc.id,
            doc_type="other",
            summary="Tax Assessment Record",
            confidence=confidence,
            needs_review=False,
            doc_metadata={"tax_info": tax_info},
        )
        db.add(doc)

    # Create TADocuments for misc documents
    for misc in result.get("misc_documents", []):
        doc = TADocument(
            org_id=org_id,
            order_id=order_id,
            raw_document_id=raw_doc.id,
            doc_type=misc.get("doc_type", "other"),
            recording_date=misc.get("recording_date"),
            recording_ref=misc.get("instrument_number") or misc.get("recording_ref"),
            summary=misc.get("description"),
            confidence=confidence,
            needs_review=confidence < 0.70,
            doc_metadata={
                "book_page": misc.get("book_page"),
                "instrument_number": misc.get("instrument_number"),
            },
        )
        db.add(doc)



async def _parse_json_property_data(
    db: AsyncSession, org_id: uuid.UUID, order_id: uuid.UUID,
    raw_doc: TARawDocument, order: TAOrder,
) -> None:
    """Parse structured JSON property data from real_data_fetcher into TADocuments.

    The JSON contains tax, assessment, legal description, and sales history
    from real county portal scraping. We also use Gemini to enrich with
    deed/mortgage detail extraction if clerk data is available.
    """
    prop_data = json.loads(raw_doc.raw_content or "{}")

    # Update order fields from fetched data
    if prop_data.get("legal_description") and not order.legal_description:
        order.legal_description = prop_data["legal_description"]
    if prop_data.get("owner_name") and not order.borrower_name:
        order.borrower_name = prop_data["owner_name"]
    if prop_data.get("parcel_number") and not order.parcel_number:
        order.parcel_number = prop_data["parcel_number"]

    confidence = 0.85  # Real portal data is high confidence

    # Create tax assessment document
    if prop_data.get("assessed_value") or prop_data.get("tax_amount"):
        tax_doc = TADocument(
            org_id=org_id,
            order_id=order_id,
            raw_document_id=raw_doc.id,
            doc_type="other",
            summary="Tax Assessment Record",
            confidence=0.95,
            needs_review=False,
            doc_metadata={
                "tax_info": {
                    "parcel_id": prop_data.get("parcel_number"),
                    "land_value": prop_data.get("land_value"),
                    "improvement_value": prop_data.get("improvement_value"),
                    "assessed_value": prop_data.get("assessed_value"),
                    "tax_amount": prop_data.get("tax_amount"),
                    "tax_year": prop_data.get("tax_year"),
                    "tax_status": prop_data.get("tax_status"),
                    "homestead_exemption": prop_data.get("homestead_exemption"),
                    "payment_history": prop_data.get("payment_history", []),
                    "subdivision": prop_data.get("subdivision"),
                }
            },
        )
        db.add(tax_doc)

    # Create documents from sales history (deed transfers)
    owner_name = prop_data.get("owner_name", "")
    sales = prop_data.get("sales_history", [])
    for i, sale in enumerate(sales):
        # For the most recent sale, the grantee is the current owner
        grantor = {"names": [sale["grantor"]]} if sale.get("grantor") else None
        grantee = {"names": [sale["grantee"]]} if sale.get("grantee") else None
        if i == 0 and owner_name and not grantee:
            grantee = {"names": [owner_name]}
        # For earlier sales, the grantor of sale N is the grantee of sale N+1
        if i > 0 and not grantee:
            prev_grantor = sales[i - 1].get("grantor")
            if prev_grantor:
                grantee = {"names": [prev_grantor]}
        doc = TADocument(
            org_id=org_id,
            order_id=order_id,
            raw_document_id=raw_doc.id,
            doc_type=sale.get("doc_type", "deed"),
            recording_date=sale.get("recording_date") or sale.get("sale_date"),
            recording_ref=sale.get("instrument_number") or sale.get("book_page"),
            grantor=grantor,
            grantee=grantee,
            consideration=sale.get("consideration") or sale.get("sale_price"),
            confidence=confidence,
            needs_review=confidence < 0.70,
            doc_metadata={
                "book_page": sale.get("book_page"),
                "instrument_number": sale.get("instrument_number"),
                "deed_type_detail": sale.get("deed_type"),
                "source": "property_appraiser",
            },
        )
        db.add(doc)

    # Create documents from recorded_documents (clerk of court)
    for rec in prop_data.get("recorded_documents", []):
        doc_type = _map_doc_type(rec.get("doc_type", ""))
        doc = TADocument(
            org_id=org_id,
            order_id=order_id,
            raw_document_id=raw_doc.id,
            doc_type=doc_type,
            recording_date=rec.get("record_date"),
            recording_ref=rec.get("instrument_number") or rec.get("book_page"),
            grantor={"names": rec["grantors"]} if rec.get("grantors") else None,
            grantee={"names": rec["grantees"]} if rec.get("grantees") else None,
            consideration=rec.get("consideration"),
            confidence=confidence,
            needs_review=confidence < 0.70,
            doc_metadata={
                "book_page": rec.get("book_page"),
                "instrument_number": rec.get("instrument_number"),
                "source": "clerk_of_court",
            },
        )
        db.add(doc)

    # Track sources that failed (for flags)
    for source in prop_data.get("sources_failed", []):
        if source.get("manual_retrieval"):
            # Create a flag for manual retrieval needed
            flag = TAFlag(
                org_id=org_id,
                order_id=order_id,
                flag_type="missing_source",
                severity="medium",
                title=f"Manual Retrieval Needed: {source.get('type', 'Unknown').replace('_', ' ').title()}",
                description=(
                    f"{source.get('type', 'Unknown source').replace('_', ' ').title()}: "
                    f"{source.get('error', 'Could not auto-retrieve')}. "
                    "Manual retrieval may be needed."
                ),
                status="open",
            )
            db.add(flag)


def _map_doc_type(raw_type: str) -> str:
    """Map clerk document type codes to TADocument doc_type values."""
    mapping = {
        "WD": "deed", "QCD": "deed", "DEED": "deed",
        "MTG": "mortgage", "ASSIGN MTG": "mortgage",
        "SAT": "satisfaction", "SATISFACTION": "satisfaction",
        "RELEASE": "satisfaction",
        "LIS": "lien", "JUDG": "lien", "FINAL JUDG": "lien",
        "NTC": "other", "NOTICE": "other",
        "EASEMENT": "other", "AFFIDAVIT": "other", "AFF": "other",
        "PLAT": "other", "SURVEY": "other",
        "AMENDMENT": "other", "AMEND": "other",
        "AGREEMENT": "other", "SUBORDINATION": "other",
        "POWER OF ATTY": "other", "DECLARATION": "other",
        "MODIFICATION": "mortgage", "COURT ORDER": "lien",
        "ASSIGN": "other",
    }
    return mapping.get(raw_type.upper(), "other")


async def _parse_text_document(
    db: AsyncSession, org_id: uuid.UUID, order_id: uuid.UUID,
    raw_doc: TARawDocument,
) -> None:
    """Parse plain text document using existing DocumentParserAgent (backward compat)."""
    from app.micro_apps.title_search.ai.document_parser_agent import DocumentParserAgent

    parser_agent = DocumentParserAgent(org_id)
    parsed = await parser_agent.parse(raw_doc.raw_content or "")
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
            "doc_metadata": d.doc_metadata,
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
            doc_metadata=d.get("doc_metadata"),
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
