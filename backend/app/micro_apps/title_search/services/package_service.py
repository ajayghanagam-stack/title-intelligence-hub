import os
import uuid
import json
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

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


# ---------------------------------------------------------------------------
# PDF helper utilities
# ---------------------------------------------------------------------------

# Light blue matching the sample: RGB(180, 198, 231)
_HEADER_BG = (180, 198, 231)
_ROW_H = 7  # default row height
_FONT = "Helvetica"


def _clean(text: str | None) -> str:
    """Make text safe for latin-1 encoding used by fpdf2."""
    if not text:
        return ""
    return text.encode("latin-1", errors="replace").decode("latin-1")


def _party_names(party: dict | None) -> str:
    """Extract comma-separated names from a party JSONB dict."""
    if not party:
        return "N/A"
    names = party.get("names", [])
    return ", ".join(names) if names else "N/A"


def _fmt_money(amount: float | None) -> str:
    """Format a float as $X,XXX.XX or N/A."""
    if amount is None:
        return "N/A"
    return f"${amount:,.2f}"


def _fmt_doc_type(doc_type: str | None) -> str:
    """Title-case a doc_type slug, e.g. 'deed' -> 'Warranty Deed'."""
    if not doc_type:
        return "N/A"
    mapping = {
        "deed": "Warranty Deed",
        "mortgage": "Mortgage",
        "lien": "Lien",
        "satisfaction": "Satisfaction",
        "easement": "Easement",
        "hoa": "HOA Document",
        "judgment": "Judgment",
        "court_order": "Court Order",
        "plat": "Plat Map",
        "other": "Other",
    }
    return mapping.get(doc_type, doc_type.replace("_", " ").title())


def _section_header(pdf, title: str, w: float) -> None:
    """Render a light-blue section header row spanning full width."""
    pdf.set_fill_color(*_HEADER_BG)
    pdf.set_font(_FONT, "BU", 10)
    pdf.cell(
        w, _ROW_H + 1, _clean(title), border=1, align="C",
        new_x="LMARGIN", new_y="NEXT", fill=True,
    )
    pdf.set_font(_FONT, "", 8)


def _label_value_row(pdf, label: str, value: str, w: float) -> None:
    """Full-width label:value row (label ~35%, value ~65%)."""
    lw = w * 0.35
    vw = w * 0.65
    pdf.set_font(_FONT, "B", 8)
    x = pdf.get_x()
    y = pdf.get_y()
    # Use multi_cell for value to handle wrapping
    # First, calculate value height
    pdf.set_font(_FONT, "", 8)
    # Estimate lines needed for value
    val_clean = _clean(value)
    label_clean = _clean(label)

    # Calculate number of lines for value text
    val_lines = pdf.multi_cell(vw, _ROW_H, val_clean, dry_run=True, output="LINES")
    num_lines = len(val_lines) if val_lines else 1
    row_h = max(_ROW_H, _ROW_H * num_lines)

    # Draw label cell
    pdf.set_xy(x, y)
    pdf.set_font(_FONT, "B", 8)
    pdf.cell(lw, row_h, label_clean, border=1, new_x="END", new_y="TOP")

    # Draw value cell with multi_cell for wrapping
    pdf.set_font(_FONT, "", 8)
    pdf.set_xy(x + lw, y)
    pdf.multi_cell(vw, _ROW_H, val_clean, border=1, new_x="LMARGIN", new_y="NEXT")

    # Ensure we're at the right Y position
    expected_y = y + row_h
    if pdf.get_y() < expected_y:
        pdf.set_y(expected_y)


def _split_row(
    pdf, l1: str, v1: str, l2: str, v2: str, w: float
) -> None:
    """Two label:value pairs side by side in one row."""
    col = w / 4
    pdf.set_font(_FONT, "B", 8)
    pdf.cell(col, _ROW_H, _clean(l1), border=1, new_x="END", new_y="TOP")
    pdf.set_font(_FONT, "", 8)
    pdf.cell(col, _ROW_H, _clean(v1), border=1, new_x="END", new_y="TOP")
    pdf.set_font(_FONT, "B", 8)
    pdf.cell(col, _ROW_H, _clean(l2), border=1, new_x="END", new_y="TOP")
    pdf.set_font(_FONT, "", 8)
    pdf.cell(col, _ROW_H, _clean(v2), border=1, new_x="LMARGIN", new_y="NEXT")


def _text_block_row(pdf, text: str, w: float) -> None:
    """Full-width bordered text row for free-text content."""
    pdf.set_font(_FONT, "", 8)
    pdf.multi_cell(w, _ROW_H, _clean(text), border=1, new_x="LMARGIN", new_y="NEXT")


def _find_logo_path() -> str | None:
    """Locate the Logikality logo PNG from known paths."""
    candidates = [
        Path(__file__).resolve().parents[5] / "frontend" / "public" / "logikality_logo.png",
        Path(__file__).resolve().parents[4] / "frontend" / "public" / "logikality_logo.png",
    ]
    for p in candidates:
        if p.is_file():
            return str(p)
    return None


def _build_doc_lookup(documents: list, chain_links: list) -> dict:
    """Build a dict mapping document_id -> TADocument for quick lookups."""
    return {str(doc.id): doc for doc in documents}


def _doc_meta(doc, key: str, default: str = "N/A") -> str:
    """Safely extract a doc_metadata field from a TADocument."""
    if doc and doc.doc_metadata and isinstance(doc.doc_metadata, dict):
        val = doc.doc_metadata.get(key)
        if val:
            return str(val)
    return default


# ---------------------------------------------------------------------------
# Main PDF generation
# ---------------------------------------------------------------------------

async def generate_package_pdf(
    db: AsyncSession, org_id: uuid.UUID, order_id: uuid.UUID
) -> bytes:
    """Generate a professional PDF report matching the Full Search Sample format."""
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

    doc_map = _build_doc_lookup(documents, chain_links)

    # Classify documents by type
    deed_docs = [d for d in documents if d.doc_type in ("deed",)]
    mortgage_docs = [d for d in documents if d.doc_type in ("mortgage",)]
    lien_docs = [d for d in documents if d.doc_type in ("lien", "judgment")]
    easement_docs = [d for d in documents if d.doc_type in ("easement",)]
    misc_docs = [d for d in documents if d.doc_type in ("other", "hoa", "plat", "court_order")]

    # Find vesting deed (most recent deed by recording_date)
    vesting_deed = None
    if deed_docs:
        vesting_deed = max(deed_docs, key=lambda d: d.recording_date or "")

    # Chain of title deeds (all conveyance links except the vesting deed)
    chain_conveyance_links = [
        link for link in chain_links
        if link.link_type == "conveyance"
        and (not vesting_deed or str(link.document_id) != str(vesting_deed.id))
    ]

    # Determine borrower name: prefer user-provided, fall back to vesting deed grantee
    borrower_name = order.borrower_name or "N/A"
    if borrower_name == "N/A" and vesting_deed:
        borrower_name = _party_names(vesting_deed.grantee)

    # Build the PDF
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    w = pdf.epw  # effective page width (within margins)
    now = datetime.now(timezone.utc)
    order_date = now.strftime("%m/%d/%Y")
    if hasattr(order, "created_at") and order.created_at:
        order_date = order.created_at.strftime("%m/%d/%Y")

    # ---- Header: Logo + Order info ----
    logo_path = _find_logo_path()
    if logo_path:
        # Logo top-right
        pdf.image(logo_path, x=pdf.w - 55, y=10, w=45)

    pdf.set_font(_FONT, "", 10)
    scope_label = (order.search_scope or "full").replace("_", " ").title()
    pdf.cell(0, 6, _clean(f"Product Type: {scope_label} Search"), new_x="LMARGIN", new_y="NEXT")
    order_ref = order.order_reference or pkg.package_number
    pdf.cell(
        0, 6,
        _clean(f"Order/Loan#: {order_ref}"),
        new_x="LMARGIN", new_y="NEXT",
    )

    # Order date right-aligned on same line area
    pdf.set_xy(pdf.w - 70, pdf.get_y() - 12)
    pdf.cell(60, 6, _clean(f"Order Date: {order_date}"), align="R")
    pdf.set_xy(pdf.l_margin, pdf.get_y() + 14)
    pdf.ln(2)

    # ---- 1. PROPERTY INFORMATION ----
    _section_header(pdf, "PROPERTY INFORMATION", w)
    _label_value_row(pdf, "Borrower's Name:", borrower_name, w)
    _label_value_row(pdf, "Property Address:", order.property_address or "N/A", w)

    municipality = order.city or "N/A"
    zip_code = order.zip_code or "N/A"
    _split_row(pdf, "Municipality:", municipality, "Zip:", zip_code, w)
    _split_row(pdf, "State:", order.state_code or "N/A", "County:", order.county or "N/A", w)

    parcel = order.parcel_number or "N/A"
    # Try to get subdivision from package property_summary or vesting deed metadata
    subdivision = "N/A"
    if pkg.property_summary and isinstance(pkg.property_summary, dict):
        subdivision = pkg.property_summary.get("subdivision", "N/A") or "N/A"
    if subdivision == "N/A" and vesting_deed:
        subdivision = _doc_meta(vesting_deed, "subdivision")
    _split_row(pdf, "Parcel Number:", parcel, "Subdivision:", subdivision, w)

    # Search dates — compute searched_from_date from effective_date - search_years
    eff_date = order.effective_date
    if not eff_date and hasattr(order, "created_at") and order.created_at:
        eff_date = order.created_at.date() if hasattr(order.created_at, "date") else order.created_at
    if eff_date:
        effective_date_str = eff_date.strftime("%m/%d/%Y")
        years = order.search_years or 60
        search_from_dt = eff_date.replace(year=eff_date.year - years)
        search_from = search_from_dt.strftime("%m/%d/%Y")
    else:
        effective_date_str = order_date
        search_from = "N/A"
    _split_row(pdf, "Searched From Date:", search_from, "Effective Date:", effective_date_str, w)

    # Short Legal
    short_legal = order.legal_description or "N/A"
    if len(short_legal) > 80:
        short_legal = short_legal[:80] + "..."
    _label_value_row(pdf, "Short Legal:", short_legal, w)
    pdf.ln(3)

    # ---- 2. VESTING DEED INFORMATION ----
    _section_header(pdf, "VESTING DEED INFORMATION", w)
    if vesting_deed:
        _split_row(
            pdf, "Deed Type:", _fmt_doc_type(vesting_deed.doc_type),
            "Consideration Amount:", _fmt_money(vesting_deed.consideration), w,
        )
        _label_value_row(pdf, "Grantor Name:", _party_names(vesting_deed.grantor), w)
        _label_value_row(pdf, "Grantee Name:", _party_names(vesting_deed.grantee), w)
        _label_value_row(pdf, "Fee Simple/leasehold:", "Fee Simple", w)
        _split_row(
            pdf, "Dated Date:", vesting_deed.recording_date or "N/A",
            "Recorded Date:", vesting_deed.recording_date or "N/A", w,
        )
        book_page = _doc_meta(vesting_deed, "book_page")
        instrument_no = _doc_meta(vesting_deed, "instrument_number", vesting_deed.recording_ref or "N/A")
        _split_row(
            pdf, "Book/Page No:", book_page,
            "Instrument No:", instrument_no, w,
        )
        _label_value_row(pdf, "Comments:", "", w)
    else:
        _text_block_row(pdf, "No vesting deed found.", w)
    pdf.ln(3)

    # ---- 3. REFERENCE OF LEGAL DESCRIPTION ----
    _section_header(pdf, "REFERENCE OF LEGAL DESCRIPTION", w)
    if vesting_deed:
        _split_row(
            pdf, "Dated Date:", vesting_deed.recording_date or "N/A",
            "Recorded Date:", vesting_deed.recording_date or "N/A", w,
        )
        book_page = _doc_meta(vesting_deed, "book_page")
        instrument_no = _doc_meta(vesting_deed, "instrument_number", vesting_deed.recording_ref or "N/A")
        _split_row(
            pdf, "Book/Page No:", book_page,
            "Instrument No:", instrument_no, w,
        )
    else:
        _text_block_row(pdf, "N/A", w)
    pdf.ln(3)

    # ---- 4. CHAIN OF TITLE (full search only) ----
    is_full_search = (order.search_scope or "full") == "full"
    if is_full_search:
        if chain_conveyance_links:
            for link in chain_conveyance_links:
                doc = doc_map.get(str(link.document_id)) if link.document_id else None
                _section_header(pdf, "CHAIN OF TITLE", w)
                doc_type = _fmt_doc_type(doc.doc_type) if doc else "N/A"
                consideration = _fmt_money(doc.consideration) if doc else "N/A"
                _split_row(pdf, "Deed Type:", doc_type, "Consideration Amount:", consideration, w)
                _label_value_row(pdf, "Grantor Name:", _party_names(link.from_party), w)
                _label_value_row(pdf, "Grantee Name:", _party_names(link.to_party), w)
                _label_value_row(pdf, "Fee Simple/leasehold:", "Fee Simple", w)
                rec_date = link.effective_date or (doc.recording_date if doc else None) or "N/A"
                rec_ref = (doc.recording_ref if doc else None) or "N/A"
                _split_row(pdf, "Dated Date:", rec_date, "Recorded Date:", rec_date, w)
                chain_book_page = _doc_meta(doc, "book_page") if doc else "N/A"
                chain_instrument = _doc_meta(doc, "instrument_number", rec_ref) if doc else rec_ref
                _split_row(pdf, "Book/Page No:", chain_book_page, "Instrument No:", chain_instrument, w)
                comments = ""
                if link.is_gap:
                    comments = f"GAP: {link.gap_description or 'Gap detected in chain'}"
                _label_value_row(pdf, "Comments:", comments, w)
                pdf.ln(3)
        else:
            _section_header(pdf, "CHAIN OF TITLE", w)
            _text_block_row(pdf, "No additional chain of title entries.", w)
            pdf.ln(3)

    # ---- 5. DEED OF TRUST/MORTGAGE INFORMATION ----
    _section_header(pdf, "DEED OF TRUST/MORTGAGE INFORMATION", w)
    if mortgage_docs:
        for mdoc in mortgage_docs:
            _label_value_row(pdf, "Borrower's Name:", _party_names(mdoc.grantee), w)
            _label_value_row(pdf, "Lender Name:", _party_names(mdoc.grantor), w)
            _label_value_row(pdf, "Trustee Name:", _doc_meta(mdoc, "trustee"), w)
            _split_row(
                pdf, "Dated Date:", mdoc.recording_date or "N/A",
                "Recorded Date:", mdoc.recording_date or "N/A", w,
            )
            instrument_no = _doc_meta(mdoc, "instrument_number", mdoc.recording_ref or "N/A")
            book_page = _doc_meta(mdoc, "book_page")
            _split_row(
                pdf, "Instrument No:", instrument_no,
                "Book/Page No:", book_page, w,
            )
            maturity = _doc_meta(mdoc, "maturity_date")
            _split_row(
                pdf, "Loan Amount:", _fmt_money(mdoc.consideration),
                "Maturity Date:", maturity, w,
            )
            open_closed = _doc_meta(mdoc, "open_closed_end")
            min_num = _doc_meta(mdoc, "min_number")
            _split_row(pdf, "Open End/Closed End:", open_closed, "MIN Number:", min_num, w)
            riders = _doc_meta(mdoc, "riders")
            _label_value_row(pdf, "PUD/Family/Home/FHA Rider:", riders, w)
            assoc_docs = _doc_meta(mdoc, "associated_docs", "")
            _label_value_row(pdf, "Associated Documents:", assoc_docs, w)
            comments = _doc_meta(mdoc, "comments", "")
            _label_value_row(pdf, "Comments:", comments, w)
            pdf.ln(2)
    else:
        _text_block_row(pdf, "N/A", w)
    pdf.ln(3)

    # ---- 6. JUDGMENT & LIEN'S INFORMATION ----
    _section_header(pdf, "JUDGMENT & LIEN'S INFORMATION", w)
    judgment_flags = [f for f in flags if f.flag_type in ("unreleased_mortgage", "lien")]
    if lien_docs or judgment_flags:
        for ldoc in lien_docs:
            _text_block_row(
                pdf,
                f"{_fmt_doc_type(ldoc.doc_type)}: {ldoc.recording_ref or 'N/A'} "
                f"({ldoc.recording_date or 'N/A'}) - {_party_names(ldoc.grantor)} "
                f"vs {_party_names(ldoc.grantee)} "
                f"Amount: {_fmt_money(ldoc.consideration)}",
                w,
            )
        for jf in judgment_flags:
            if not lien_docs:
                _text_block_row(pdf, f"[{jf.severity.upper()}] {jf.title}: {jf.description}", w)
    else:
        _text_block_row(pdf, "NA", w)
    pdf.ln(3)

    # ---- 7. TAX INFORMATION ----
    _section_header(pdf, "TAX INFORMATION", w)
    # Look for a document with tax_info in metadata
    tax_doc = next(
        (d for d in documents if d.doc_metadata and isinstance(d.doc_metadata, dict) and d.doc_metadata.get("tax_info")),
        None,
    )
    if tax_doc:
        ti = tax_doc.doc_metadata["tax_info"]
        _split_row(
            pdf, "Parcel ID:", str(ti.get("parcel_id", "N/A")),
            "Assessment Year:", str(ti.get("assessment_year", "N/A")), w,
        )
        _split_row(
            pdf, "Land Value:", _fmt_money(ti.get("land_value")),
            "Improvement Value:", _fmt_money(ti.get("improvement_value")), w,
        )
        _split_row(
            pdf, "Total Assessed Value:", _fmt_money(ti.get("total_value")),
            "Tax Amount:", _fmt_money(ti.get("tax_amount")), w,
        )
        _split_row(
            pdf, "Tax Status:", str(ti.get("tax_status", "N/A")),
            "Homestead:", "Yes" if ti.get("homestead_exemption") else "No", w,
        )
    else:
        _text_block_row(pdf, "Tax information not available in current data.", w)
    pdf.ln(3)

    # ---- 8. EXCEPTIONS/EASEMENTS DOCUMENTS ----
    _section_header(pdf, "EXCEPTIONS/EASEMENTS DOCUMENTS", w)
    if easement_docs:
        for edoc in easement_docs:
            _text_block_row(
                pdf,
                f"{_fmt_doc_type(edoc.doc_type)}: {edoc.recording_ref or 'N/A'} "
                f"({edoc.recording_date or 'N/A'}) - {edoc.summary or ''}",
                w,
            )
    else:
        _text_block_row(pdf, "N/A", w)
    pdf.ln(3)

    # ---- 9. MISCELLANEOUS DOCUMENTS ----
    _section_header(pdf, "MISCELLANEOUS DOCUMENTS", w)
    if misc_docs:
        for i, mdoc in enumerate(misc_docs, 1):
            desc = mdoc.summary or f"{_fmt_doc_type(mdoc.doc_type)}: {mdoc.recording_ref or 'N/A'}"
            _text_block_row(pdf, f"{i}. {desc}", w)
    else:
        _text_block_row(pdf, "N/A", w)
    pdf.ln(3)

    # ---- 10. LEGAL DESCRIPTION ----
    _section_header(pdf, "LEGAL DESCRIPTION", w)
    _text_block_row(pdf, order.legal_description or "N/A", w)
    pdf.ln(3)

    # ---- 11. NAMES SEARCH ----
    _section_header(pdf, "NAMES SEARCH", w)
    all_names: set[str] = set()
    for doc in documents:
        if doc.grantor:
            for name in doc.grantor.get("names", []):
                all_names.add(name)
        if doc.grantee:
            for name in doc.grantee.get("names", []):
                all_names.add(name)
    if all_names:
        names_text = "\n".join(sorted(all_names))
        _text_block_row(pdf, names_text, w)
    else:
        _text_block_row(pdf, "N/A", w)
    pdf.ln(3)

    # ---- 12. ADDITIONAL COMMENTS ----
    _section_header(pdf, "ADDITIONAL COMMENTS", w)
    narrative = ""
    if hasattr(pkg, "property_summary") and pkg.property_summary:
        narrative = pkg.property_summary.get("narrative", "")
    _text_block_row(pdf, narrative or "N/A", w)

    return bytes(pdf.output())
