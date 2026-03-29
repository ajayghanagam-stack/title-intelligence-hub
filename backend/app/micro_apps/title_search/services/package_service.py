import uuid
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

_HEADER_BG = (230, 126, 34)  # Logikality brand orange
_HEADER_FG = (255, 255, 255)  # White text on orange
_ROW_H = 7
_FONT = "Helvetica"


def _clean(text: str | None) -> str:
    if not text:
        return ""
    return text.encode("latin-1", errors="replace").decode("latin-1")


def _party_names(party: dict | None) -> str:
    if not party:
        return "N/A"
    names = party.get("names", [])
    return ", ".join(names) if names else "N/A"


def _fmt_money(amount) -> str:
    if amount is None:
        return "N/A"
    try:
        return f"${float(amount):,.2f}"
    except (ValueError, TypeError):
        return "N/A"


def _fmt_doc_type(doc_type: str | None) -> str:
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


def _deed_type_label(doc) -> str:
    """Get the best deed type label for a document."""
    # Check deed_type_detail in metadata first (e.g. "SW - Special Warranty")
    dtd = _doc_meta(doc, "deed_type_detail", "")
    if dtd and dtd != "N/A":
        # Clean up codes like "SW - Special Warranty" to just the name
        if " - " in dtd:
            return dtd.split(" - ", 1)[1]
        return dtd
    return _fmt_doc_type(doc.doc_type)


def _section_header(pdf, title: str, w: float) -> None:
    _ensure_space(pdf, _ROW_H + 5)
    pdf.set_fill_color(*_HEADER_BG)
    pdf.set_text_color(*_HEADER_FG)
    pdf.set_font(_FONT, "B", 10)
    pdf.cell(
        w, _ROW_H + 1, _clean(title), border=1, align="C",
        new_x="LMARGIN", new_y="NEXT", fill=True,
    )
    pdf.set_text_color(0, 0, 0)  # Reset to black
    pdf.set_font(_FONT, "", 8)


def _ensure_space(pdf, needed: float) -> None:
    """Add a new page if there's not enough vertical space remaining."""
    remaining = pdf.h - pdf.get_y() - pdf.b_margin
    if remaining < needed:
        pdf.add_page()


def _label_value_row(pdf, label: str, value: str, w: float) -> None:
    lw = w * 0.35
    vw = w * 0.65
    val_clean = _clean(value)
    label_clean = _clean(label)

    pdf.set_font(_FONT, "", 8)
    val_lines = pdf.multi_cell(vw, _ROW_H, val_clean, dry_run=True, output="LINES")
    num_lines = len(val_lines) if val_lines else 1
    row_h = max(_ROW_H, _ROW_H * num_lines)

    _ensure_space(pdf, row_h + 2)

    x, y = pdf.get_x(), pdf.get_y()
    pdf.set_font(_FONT, "B", 8)
    pdf.cell(lw, row_h, label_clean, border=1, new_x="END", new_y="TOP")
    pdf.set_font(_FONT, "", 8)
    pdf.set_xy(x + lw, y)
    pdf.multi_cell(vw, _ROW_H, val_clean, border=1, new_x="LMARGIN", new_y="NEXT")

    expected_y = y + row_h
    if pdf.get_y() < expected_y:
        pdf.set_y(expected_y)


def _split_row(pdf, l1, v1, l2, v2, w) -> None:
    _ensure_space(pdf, _ROW_H + 2)
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
    pdf.set_font(_FONT, "", 8)
    pdf.multi_cell(w, _ROW_H, _clean(text), border=1, new_x="LMARGIN", new_y="NEXT")


def _find_logo_path() -> str | None:
    # Prefer the high-res converted PNG from the SVG source
    candidates = [
        Path(__file__).parent / "logikality_logo.png",
        Path(__file__).resolve().parents[5] / "frontend" / "public" / "logikality_logo.png",
        Path(__file__).resolve().parents[4] / "frontend" / "public" / "logikality_logo.png",
    ]
    for p in candidates:
        if p.is_file():
            return str(p)
    return None


def _doc_meta(doc, key: str, default: str = "N/A") -> str:
    if doc and doc.doc_metadata and isinstance(doc.doc_metadata, dict):
        val = doc.doc_metadata.get(key)
        if val:
            return str(val)
    return default


def _get_tax_info(documents: list) -> dict | None:
    """Find tax_info from documents metadata."""
    for d in documents:
        if d.doc_metadata and isinstance(d.doc_metadata, dict):
            ti = d.doc_metadata.get("tax_info")
            if ti:
                return ti
    return None


# ---------------------------------------------------------------------------
# Tax installment table (matches sample format)
# ---------------------------------------------------------------------------

def _render_tax_table(pdf, ti: dict, w: float) -> None:
    """Render the tax installment table from the sample PDF."""
    headers = ["Installments:", "Tax Amount:", "Status:", "Due/Paid Date:",
               "Total Amount (P&I):", "Good through Date:"]
    col_w = w / len(headers)

    # Header row
    pdf.set_font(_FONT, "B", 7)
    for h in headers:
        pdf.cell(col_w, _ROW_H, _clean(h), border=1, new_x="END", new_y="TOP")
    pdf.ln(_ROW_H)

    # Data row
    pdf.set_font(_FONT, "", 7)
    tax_amt = _fmt_money(ti.get("tax_amount"))
    status = str(ti.get("tax_status", "N/A") or "N/A")
    # Try to get paid date from payment history
    paid_date = ""
    history = ti.get("payment_history", [])
    if history and isinstance(history, list) and len(history) > 0:
        first = history[0]
        if isinstance(first, dict):
            paid_date = first.get("payment_date", "")

    values = ["Annual", tax_amt, status, paid_date, "", ""]
    for v in values:
        pdf.cell(col_w, _ROW_H, _clean(v), border=1, new_x="END", new_y="TOP")
    pdf.ln(_ROW_H)


# ---------------------------------------------------------------------------
# Main PDF generation
# ---------------------------------------------------------------------------

async def generate_package_pdf(
    db: AsyncSession, org_id: uuid.UUID, order_id: uuid.UUID
) -> bytes:
    """Generate a professional PDF report matching the Logikality sample format."""
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

    doc_map = {str(doc.id): doc for doc in documents}

    # Classify documents
    deed_docs = [d for d in documents if d.doc_type == "deed"]
    mortgage_docs = [d for d in documents if d.doc_type == "mortgage"]
    lien_docs = [d for d in documents if d.doc_type in ("lien", "judgment")]
    easement_docs = [d for d in documents if d.doc_type == "easement"]
    misc_docs = [d for d in documents if d.doc_type in ("other", "hoa", "plat", "court_order")]
    # Exclude tax assessment records from misc
    misc_docs = [d for d in misc_docs if not (d.summary and "Tax Assessment" in d.summary)]

    # Vesting deed = most recent deed by recording_date
    vesting_deed = None
    if deed_docs:
        def _date_sort_key(d):
            """Parse various date formats for sorting."""
            rd = d.recording_date or ""
            for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
                try:
                    from datetime import datetime as dt
                    return dt.strptime(rd, fmt)
                except ValueError:
                    continue
            return datetime.min
        vesting_deed = max(deed_docs, key=_date_sort_key)

    # Chain deeds (all except the vesting deed)
    chain_conveyance_links = [
        link for link in chain_links
        if link.link_type == "conveyance"
        and (not vesting_deed or str(link.document_id) != str(vesting_deed.id))
    ]

    # Borrower name
    borrower_name = order.borrower_name or "N/A"
    if borrower_name == "N/A" and vesting_deed:
        borrower_name = _party_names(vesting_deed.grantee)

    is_full_search = (order.search_scope or "full") == "full"

    # Tax info
    ti = _get_tax_info(documents)

    # Subdivision from tax_info or package summary
    subdivision = "N/A"
    if ti and ti.get("subdivision"):
        subdivision = ti["subdivision"]
    elif pkg.property_summary and isinstance(pkg.property_summary, dict):
        subdivision = pkg.property_summary.get("subdivision", "N/A") or "N/A"
    if subdivision == "N/A" and vesting_deed:
        subdivision = _doc_meta(vesting_deed, "subdivision")

    # Build PDF
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    w = pdf.epw
    now = datetime.now(timezone.utc)
    order_date = now.strftime("%m/%d/%Y")
    if hasattr(order, "created_at") and order.created_at:
        order_date = order.created_at.strftime("%m/%d/%Y")

    # ---- Header: Logo + Order info ----
    logo_path = _find_logo_path()
    if logo_path:
        pdf.image(logo_path, x=pdf.w - 55, y=10, w=45)

    pdf.set_font(_FONT, "", 10)
    scope_label = "Full Search" if is_full_search else "Current Owner Search"
    pdf.cell(0, 6, _clean(f"Product Type: {scope_label}"), new_x="LMARGIN", new_y="NEXT")
    order_ref = order.order_reference or pkg.package_number
    pdf.cell(0, 6, _clean(f"Order/Loan#: {order_ref}"), new_x="LMARGIN", new_y="NEXT")

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
    _split_row(pdf, "Parcel Number:", parcel, "Subdivision:", subdivision, w)

    # Dates
    eff_date = order.effective_date
    if not eff_date and hasattr(order, "created_at") and order.created_at:
        eff_date = order.created_at.date() if hasattr(order.created_at, "date") else order.created_at
    if eff_date:
        effective_date_str = eff_date.strftime("%m/%d/%Y")
        years = order.search_years or 60
        try:
            search_from_dt = eff_date.replace(year=eff_date.year - years)
            search_from = search_from_dt.strftime("%m/%d/%Y")
        except ValueError:
            search_from = "N/A"
    else:
        effective_date_str = order_date
        search_from = "N/A"
    _split_row(pdf, "Searched From Date:", search_from, "Effective Date:", effective_date_str, w)

    short_legal = order.legal_description or "N/A"
    if len(short_legal) > 80:
        short_legal = short_legal[:80] + "..."
    _label_value_row(pdf, "Short Legal:", short_legal, w)
    pdf.ln(3)

    # ---- 2. VESTING DEED INFORMATION ----
    _section_header(pdf, "VESTING DEED INFORMATION", w)
    if vesting_deed:
        deed_label = _deed_type_label(vesting_deed)
        _split_row(
            pdf, "Deed Type:", deed_label,
            "Consideration Amount:", _fmt_money(vesting_deed.consideration), w,
        )
        _label_value_row(pdf, "Grantor Name:", _party_names(vesting_deed.grantor), w)
        _label_value_row(pdf, "Grantee Name:", _party_names(vesting_deed.grantee), w)
        _label_value_row(pdf, "Fee Simple/leasehold:", "Fee Simple", w)

        rec_date = vesting_deed.recording_date or "N/A"
        _split_row(pdf, "Dated Date:", rec_date, "Recorded Date:", rec_date, w)

        book_page = _doc_meta(vesting_deed, "book_page")
        inst_no = _doc_meta(vesting_deed, "instrument_number", vesting_deed.recording_ref or "N/A")
        _split_row(pdf, " Book/Page No:", book_page, "Instrument No:", inst_no, w)
        _label_value_row(pdf, "Comments:", "", w)
    else:
        _text_block_row(pdf, "No vesting deed found.", w)
    pdf.ln(3)

    # ---- 3. REFERENCE OF LEGAL DESCRIPTION ----
    _section_header(pdf, "REFERENCE OF LEGAL DESCRIPTION", w)
    if vesting_deed:
        rec_date = vesting_deed.recording_date or "N/A"
        _split_row(pdf, "Dated Date:", rec_date, "Recorded Date:", rec_date, w)
        book_page = _doc_meta(vesting_deed, "book_page")
        inst_no = _doc_meta(vesting_deed, "instrument_number", vesting_deed.recording_ref or "N/A")
        _split_row(pdf, " Book/Page No:", book_page, "Instrument No:", inst_no, w)
    else:
        _text_block_row(pdf, "N/A", w)
    pdf.ln(3)

    # ---- 4. CHAIN OF TITLE (Full Search only) ----
    if is_full_search:
        if chain_conveyance_links:
            for link in chain_conveyance_links:
                doc = doc_map.get(str(link.document_id)) if link.document_id else None
                _section_header(pdf, "CHAIN OF TITLE", w)
                doc_type = _fmt_doc_type(doc.doc_type) if doc else "N/A"
                if doc:
                    doc_type = _deed_type_label(doc)
                consideration = _fmt_money(doc.consideration) if doc else "N/A"
                _split_row(pdf, "Deed Type:", doc_type, "Consideration Amount:", consideration, w)

                # Grantor: chain link from_party → fall back to document grantor
                from_names = _party_names(link.from_party) if isinstance(link.from_party, dict) else (link.from_party or "")
                if (not from_names or from_names == "N/A") and doc and doc.grantor:
                    from_names = _party_names(doc.grantor)
                _label_value_row(pdf, "Grantor Name:", from_names or "N/A", w)

                # Grantee: chain link to_party → fall back to document grantee
                to_names = _party_names(link.to_party) if isinstance(link.to_party, dict) else (link.to_party or "")
                if (not to_names or to_names == "N/A") and doc and doc.grantee:
                    to_names = _party_names(doc.grantee)
                _label_value_row(pdf, "Grantee Name:", to_names or "N/A", w)

                _label_value_row(pdf, "Fee Simple/leasehold:", "Fee Simple", w)
                rec_date = link.effective_date or (doc.recording_date if doc else None) or "N/A"
                _split_row(pdf, "Dated Date:", rec_date, "Recorded Date:", rec_date, w)

                # Book/Page and Instrument: doc_metadata → recording_ref
                chain_book_page = "N/A"
                chain_instrument = "N/A"
                if doc:
                    chain_book_page = _doc_meta(doc, "book_page", doc.recording_ref or "N/A")
                    chain_instrument = _doc_meta(doc, "instrument_number", doc.recording_ref or "N/A")
                _split_row(pdf, " Book/Page No:", chain_book_page, "Instrument No:", chain_instrument, w)

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
            # In mortgages: grantor = borrower, grantee = lender
            borrower = _party_names(mdoc.grantee) if mdoc.grantee else "N/A"
            lender = _party_names(mdoc.grantor) if mdoc.grantor else "N/A"
            # Swap if the source is clerk (clerk: "From" = borrower, "To" = lender)
            source = _doc_meta(mdoc, "source")
            if source == "clerk_of_court":
                borrower = _party_names(mdoc.grantor) if mdoc.grantor else "N/A"
                lender = _party_names(mdoc.grantee) if mdoc.grantee else "N/A"
            _label_value_row(pdf, "Borrower's Name:", borrower, w)
            _label_value_row(pdf, "Lender Name:", lender, w)
            _label_value_row(pdf, "Trustee Name:", _doc_meta(mdoc, "trustee"), w)
            rec_date = mdoc.recording_date or "N/A"
            _split_row(pdf, "Dated Date:", rec_date, "Recorded Date:", rec_date, w)
            inst_no = _doc_meta(mdoc, "instrument_number", mdoc.recording_ref or "N/A")
            book_page = _doc_meta(mdoc, "book_page")
            _split_row(pdf, "Instrument No:", inst_no, "Book/Page No:", book_page, w)
            maturity = _doc_meta(mdoc, "maturity_date")
            _split_row(pdf, "Loan Amount:", _fmt_money(mdoc.consideration), "Maturity Date:", maturity, w)
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
        has_captcha = any(
            sf.get("captcha_blocked") for sf in (pkg.property_summary or {}).get("sources_failed", [])
            if isinstance(sf, dict)
        )
        if has_captcha:
            _text_block_row(
                pdf,
                "Mortgage records not available - clerk portal access was blocked. "
                "Manual retrieval required.", w,
            )
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
    if ti:
        parcel_id = str(ti.get("parcel_id", "N/A") or "N/A")
        tax_year = str(ti.get("tax_year", "N/A") or "N/A")
        # Assessment year defaults to tax year
        assessment_year = str(ti.get("assessment_year", tax_year) or tax_year)

        _split_row(pdf, "Parcel ID:", parcel_id, "Assessment Year:", assessment_year, w)
        _split_row(pdf, "Tax Year:", tax_year, "", "", w)
        _split_row(
            pdf, "Land Value:", _fmt_money(ti.get("land_value")),
            "Improvement Value:", _fmt_money(ti.get("improvement_value")), w,
        )
        total_value = ti.get("total_value") or ti.get("assessed_value")
        _split_row(
            pdf, "Total Value:", _fmt_money(total_value),
            "Homestead Exemption:", "Yes" if ti.get("homestead_exemption") else "NA", w,
        )

        # Blank lines for other exemption as in sample
        _split_row(pdf, "Other Exemption:", "NA", "", "", w)
        pdf.ln(1)

        # Tax installment table
        _render_tax_table(pdf, ti, w)

        _label_value_row(pdf, "Comments:", "", w)
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
    # Include plat docs in misc section as "Plat Map recorded in B/P X/Y"
    plat_docs = [d for d in documents if d.doc_type == "plat" or (
        d.doc_metadata and isinstance(d.doc_metadata, dict)
        and d.doc_metadata.get("deed_type_detail", "").startswith("PB")
    )]
    all_misc = list(misc_docs)
    # Add plat docs that aren't already in misc
    misc_ids = {str(d.id) for d in all_misc}
    for pd in plat_docs:
        if str(pd.id) not in misc_ids:
            all_misc.append(pd)

    if all_misc:
        for i, mdoc in enumerate(all_misc, 1):
            if mdoc.doc_type == "plat" or (
                mdoc.doc_metadata and isinstance(mdoc.doc_metadata, dict)
                and mdoc.doc_metadata.get("deed_type_detail", "").startswith("PB")
            ):
                bp = _doc_meta(mdoc, "book_page", mdoc.recording_ref or "N/A")
                desc = f"Plat Map is Recorded in B/P {bp}"
            else:
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
    # Collect from documents
    for doc in documents:
        if doc.grantor:
            for name in doc.grantor.get("names", []):
                if name:
                    all_names.add(name)
        if doc.grantee:
            for name in doc.grantee.get("names", []):
                if name:
                    all_names.add(name)
    # Collect from chain links
    for link in chain_links:
        if isinstance(link.from_party, dict):
            for name in link.from_party.get("names", []):
                if name:
                    all_names.add(name)
        if isinstance(link.to_party, dict):
            for name in link.to_party.get("names", []):
                if name:
                    all_names.add(name)
    # Add subdivision name if meaningful
    if subdivision and subdivision != "N/A":
        all_names.add(subdivision)
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
    if not is_full_search:
        _text_block_row(pdf, narrative or "N/A", w)
    else:
        comment = narrative or "Please note: Search Starts from Developer Deed."
        _text_block_row(pdf, comment, w)

    return bytes(pdf.output())
