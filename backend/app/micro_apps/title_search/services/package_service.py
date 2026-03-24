import uuid
import json
from datetime import datetime, timezone
from io import BytesIO

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.micro_apps.title_search.models.order import TAOrder
from app.micro_apps.title_search.models.document import TADocument
from app.micro_apps.title_search.models.chain_link import TAChainLink
from app.micro_apps.title_search.models.flag import TAFlag
from app.micro_apps.title_search.models.package import TAPackage
from app.core.exceptions import NotFoundError, ConflictError


async def get_package_or_raise(
    db: AsyncSession, org_id: uuid.UUID, order_id: uuid.UUID
) -> TAPackage:
    result = await db.execute(
        select(TAPackage).where(
            TAPackage.order_id == order_id,
            TAPackage.org_id == org_id,
        )
    )
    pkg = result.scalar_one_or_none()
    if not pkg:
        raise NotFoundError("Package", order_id)
    return pkg


async def issue_package(
    db: AsyncSession,
    org_id: uuid.UUID,
    order_id: uuid.UUID,
    issuer_id: uuid.UUID,
) -> TAPackage:
    """Manually issue a package. Blocks if unresolved critical flags exist."""
    pkg = await get_package_or_raise(db, org_id, order_id)

    if pkg.status == "issued":
        raise ConflictError("Package is already issued")

    # Check for unresolved critical flags
    flags = (await db.execute(
        select(TAFlag).where(
            TAFlag.order_id == order_id,
            TAFlag.org_id == org_id,
            TAFlag.status == "open",
            TAFlag.severity == "critical",
        )
    )).scalars().all()

    if flags:
        raise ConflictError(
            f"Cannot issue package: {len(flags)} unresolved critical flag(s)"
        )

    pkg.status = "issued"
    pkg.issued_by = "manual"
    pkg.issued_at = datetime.now(timezone.utc)
    pkg.issuer_id = issuer_id
    await db.commit()
    await db.refresh(pkg)
    return pkg


async def generate_package_pdf(
    db: AsyncSession, org_id: uuid.UUID, order_id: uuid.UUID
) -> bytes:
    """Generate a PDF for the package."""
    pkg = await get_package_or_raise(db, org_id, order_id)

    order = (await db.execute(
        select(TAOrder).where(TAOrder.id == order_id, TAOrder.org_id == org_id)
    )).scalar_one()

    documents = (await db.execute(
        select(TADocument).where(TADocument.order_id == order_id, TADocument.org_id == org_id)
    )).scalars().all()

    chain_links = (await db.execute(
        select(TAChainLink).where(TAChainLink.order_id == order_id, TAChainLink.org_id == org_id)
        .order_by(TAChainLink.position)
    )).scalars().all()

    flags = (await db.execute(
        select(TAFlag).where(TAFlag.order_id == order_id, TAFlag.org_id == org_id)
    )).scalars().all()

    try:
        from fpdf import FPDF
    except ImportError:
        raise RuntimeError("fpdf2 is required for PDF generation")

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # Title
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "Title Search Abstract Package", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, f"Package #: {pkg.package_number}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, f"Status: {pkg.status}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)

    # Property Summary
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Property Summary", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(0, 6, f"Address: {order.property_address}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, f"County: {order.county}, {order.state_code}", new_x="LMARGIN", new_y="NEXT")
    if order.parcel_number:
        pdf.cell(0, 6, f"Parcel: {order.parcel_number}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)

    # Search Scope
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Search Scope", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, f"Scope: {order.search_scope} | Years: {order.search_years}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, f"Documents Found: {len(documents)}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)

    # Document Inventory
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Document Inventory", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    for doc in documents:
        pdf.multi_cell(
            0, 5,
            f"- {doc.doc_type.upper()}: {doc.recording_ref or 'N/A'} "
            f"({doc.recording_date or 'N/A'}) | Confidence: {doc.confidence or 'N/A'}",
            new_x="LMARGIN", new_y="NEXT",
        )
    pdf.ln(5)

    # Chain of Title
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Chain of Title", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 6, f"Complete: {'Yes' if pkg.chain_complete else 'No'}", new_x="LMARGIN", new_y="NEXT")
    for link in chain_links:
        from_names = ", ".join(link.from_party.get("names", [])) if link.from_party else "Unknown"
        to_names = ", ".join(link.to_party.get("names", [])) if link.to_party else "Unknown"
        gap_marker = " [GAP]" if link.is_gap else ""
        pdf.multi_cell(
            0, 5,
            f"{link.position}. {from_names} -> {to_names} "
            f"({link.effective_date or 'N/A'}) [{link.link_type}]{gap_marker}",
            new_x="LMARGIN", new_y="NEXT",
        )
    pdf.ln(5)

    # Flags
    if flags:
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, "Flags & Issues", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 9)
        for flag in flags:
            pdf.multi_cell(
                0, 5,
                f"[{flag.severity.upper()}] {flag.title}: {flag.description} (Status: {flag.status})",
                new_x="LMARGIN", new_y="NEXT",
            )

    return bytes(pdf.output())
