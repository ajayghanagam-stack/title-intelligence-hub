"""fpdf2 renderer for the compliance report.

Mirrors the layout of the prototype's `buildComplianceReportPDF` (jsPDF, letter
points): title block → executive summary → critical-findings callout → findings
by category (heading + finding rows) → footer disclaimer + version stamp.

Pure function: takes findings + summary + meta and returns PDF bytes. No DB,
no LLM, no I/O. Determinism: identical inputs → identical PDF (modulo the date
in the header, which is taken from `report_date` so callers can pin it for
golden-set tests).
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from fpdf import FPDF


def _find_logikality_logo() -> str | None:
    """Locate the bundled Logikality logo, mirroring the TI report helper.

    Primary path is the LO `assets/` directory shipped with the package
    (works in Docker and CI). Fallback walks up to find `frontend/public`
    so local dev still works if the asset hasn't been copied yet.
    """
    assets_dir = Path(__file__).resolve().parent.parent / "assets"
    bundled = assets_dir / "logikality_with_tagline.png"
    if bundled.is_file():
        return str(bundled)
    current = Path(__file__).resolve().parent
    while current != current.parent:
        pub = current / "frontend" / "public"
        if pub.is_dir():
            for name in ("logikality_with_tagline.png", "logikality_logo.png"):
                p = pub / name
                if p.is_file():
                    return str(p)
        current = current.parent
    return None


# Letter page in points — matches prototype `PAGE_W=612 PAGE_H=792`.
PAGE_W_PT = 612.0
PAGE_H_PT = 792.0
M_LEFT = 54.0
M_RIGHT = 54.0
M_TOP = 54.0
M_BOTTOM = 54.0
CONTENT_W = PAGE_W_PT - M_LEFT - M_RIGHT

# Logikality brand palette — mirrors `title_intelligence/services/pdf_service.py`
# so every report PDF uses the same colors. Values are sRGB (0-255) tuples
# converted from the OKLCH variables in `frontend/src/app/globals.css`.
_BRAND_AMBER = (197, 155, 0)
_BRAND_CHARCOAL = (45, 41, 36)
_BRAND_MAGENTA = (196, 46, 124)
_BRAND_PURPLE = (110, 70, 180)
_WHITE = (255, 255, 255)
_BODY = (45, 41, 36)            # primary body text — charcoal
_MUTED = (110, 110, 110)
_SUBTLE = (140, 140, 140)
_TABLE_HDR = (240, 242, 245)
_TABLE_ALT = (248, 249, 251)
_BORDER = (200, 205, 210)
_SOFT_BORDER = (220, 220, 220)

# Severity / status colors (used for inline badges in finding rows).
_SEVERITY_COLORS: dict[str, tuple[int, int, int]] = {
    "critical": (185, 28, 28),    # red-700
    "high": (180, 120, 0),        # amber-700
    "medium": (140, 105, 20),     # amber-800 dimmer
    "low": (100, 100, 100),       # neutral
}
_STATUS_COLORS: dict[str, tuple[int, int, int]] = {
    "compliant": (21, 128, 61),               # emerald-700
    "partial": (180, 120, 0),                 # amber-700
    "missing": (185, 28, 28),                 # red-700
    "attestation_required": (110, 70, 180),   # brand purple
}

# Helvetica core font is cp1252-only. Map the typographic characters that appear
# in regulation copy + rule descriptions to safe equivalents so a PDF render
# never throws on a Unicode codepoint outside cp1252.
_CP1252_FALLBACKS: dict[int, str] = {
    0x2192: "->",   # rightwards arrow
    0x2190: "<-",
    0x2194: "<->",
    0x2264: "<=",   # ≤
    0x2265: ">=",   # ≥
    0x2260: "!=",   # ≠
    0x00B1: "+/-",  # ± (cp1252-safe but kept here for legibility on some PDF readers)
    0x2013: "-",    # en dash
    0x2018: "'",    # left single quote
    0x2019: "'",    # right single quote
    0x201C: '"',    # left double quote
    0x201D: '"',    # right double quote
    0x2032: "'",    # prime
    0x2033: '"',    # double prime
}


def _safe_text(s: str) -> str:
    """Coerce arbitrary Unicode into a cp1252-safe string for the core fonts.

    First applies the known typographic fallbacks, then drops any remaining
    non-cp1252 code points (replaced with `?`). Defensive — any future rule
    copy that introduces a stray Unicode char won't crash the PDF render.
    """
    if not s:
        return ""
    out = s.translate(_CP1252_FALLBACKS)
    return out.encode("cp1252", errors="replace").decode("cp1252")


_STATUS_LABEL: dict[str, str] = {
    "compliant": "Compliant",
    "partial": "Partial",
    "missing": "Missing",
    "attestation_required": "Attestation required",
}
_SEVERITY_ORDER: dict[str, int] = {"critical": 0, "high": 1, "medium": 2, "low": 3}
_STATUS_WEIGHT: dict[str, int] = {
    "missing": 0, "partial": 1, "attestation_required": 2, "compliant": 3,
}


def _setup_pdf() -> FPDF:
    pdf = FPDF(unit="pt", format="letter")
    # cp1252 (vs the default latin-1) lets the built-in Helvetica core font
    # render the em dash (—), bullet (•), middle dot (·), and ellipsis (…)
    # used throughout the report copy without bundling a Unicode TTF.
    pdf.core_fonts_encoding = "cp1252"
    pdf.set_auto_page_break(auto=True, margin=M_BOTTOM)
    pdf.set_margins(left=M_LEFT, top=M_TOP, right=M_RIGHT)
    pdf.add_page()
    return pdf


def _write_text(
    pdf: FPDF,
    text: str,
    *,
    size: float = 10,
    style: str = "",
    color: tuple[int, int, int] = (30, 30, 30),
    line_height: float = 1.4,
    indent: float = 0,
    right_pad: float = 0,
    after: float = 0,
) -> None:
    """Wrapped text writer mirroring the prototype's `writeText` helper.

    `right_pad` reserves space on the right edge so card content doesn't run
    flush against the card border.
    """
    pdf.set_font("Helvetica", style=style, size=size)
    pdf.set_text_color(*color)
    pdf.set_x(M_LEFT + indent)
    pdf.multi_cell(
        w=CONTENT_W - indent - right_pad,
        h=size * line_height,
        txt=_safe_text(str(text or "")),
        new_x="LMARGIN",
        new_y="NEXT",
    )
    if after:
        pdf.ln(after)


def _hr(pdf: FPDF, color: tuple[int, int, int] = _SOFT_BORDER) -> None:
    pdf.set_draw_color(*color)
    pdf.set_line_width(0.6)
    y = pdf.get_y()
    pdf.line(M_LEFT, y, PAGE_W_PT - M_RIGHT, y)
    pdf.ln(8)


def _section_header(
    pdf: FPDF,
    text: str,
    *,
    fill: tuple[int, int, int] = _BRAND_AMBER,
    text_color: tuple[int, int, int] = _WHITE,
    height: float = 22,
    after: float = 8,
) -> None:
    """Filled banner header — mirrors the TI report's section banners."""
    pdf.set_fill_color(*fill)
    pdf.set_text_color(*text_color)
    pdf.set_font("Helvetica", style="B", size=12)
    pdf.set_x(M_LEFT)
    pdf.cell(
        w=CONTENT_W,
        h=height,
        txt=_safe_text(text),
        border=0,
        new_x="LMARGIN",
        new_y="NEXT",
        align="L",
        fill=True,
    )
    if after:
        pdf.ln(after)


def _pill(
    pdf: FPDF,
    text: str,
    color: tuple[int, int, int],
    *,
    pad_x: float = 4,
    height: float = 12,
) -> None:
    """Render a small colored pill at the current cursor and advance x."""
    pdf.set_font("Helvetica", style="B", size=8)
    label = _safe_text(text)
    w = pdf.get_string_width(label) + pad_x * 2
    x, y = pdf.get_x(), pdf.get_y()
    pdf.set_fill_color(*color)
    pdf.set_draw_color(*color)
    # Manually drawn rect because fpdf2's rounded-rect helper varies by version.
    pdf.rect(x, y, w, height, style="F")
    pdf.set_text_color(*_WHITE)
    pdf.set_xy(x, y + (height - 8) / 2 - 0.5)
    pdf.cell(w=w, h=8, txt=label, align="C")
    pdf.set_xy(x + w + 4, y)


def _draw_card_segment(
    pdf: FPDF,
    page_no: int,
    y0: float,
    y1: float,
    *,
    fill: tuple[int, int, int] | None,
    border: tuple[int, int, int] | None,
    accent: tuple[int, int, int] | None,
    accent_w: float,
) -> None:
    """Draw a card on a specific page, switching pages around the call."""
    if y1 - y0 <= 0:
        return
    saved_page = pdf.page
    try:
        pdf.page = page_no
        x = M_LEFT
        h = y1 - y0
        if fill is not None:
            pdf.set_fill_color(*fill)
            pdf.rect(x, y0, CONTENT_W, h, style="F")
        if border is not None:
            pdf.set_draw_color(*border)
            pdf.set_line_width(0.5)
            pdf.rect(x, y0, CONTENT_W, h, style="D")
        if accent is not None:
            pdf.set_fill_color(*accent)
            pdf.rect(x, y0, accent_w, h, style="F")
    finally:
        pdf.page = saved_page


def _draw_card(
    pdf: FPDF,
    y_start: float,
    y_end: float,
    *,
    page_start: int | None = None,
    page_end: int | None = None,
    fill: tuple[int, int, int] | None = None,
    border: tuple[int, int, int] | None = _BORDER,
    accent: tuple[int, int, int] | None = None,
    accent_w: float = 2.5,
    radius: float = 0,  # noqa: ARG001 — kept for future rounded-rect support
) -> None:
    """Draw a bordered card behind already-rendered content.

    If the content spanned a page break (`page_start != page_end`), the card
    is split into per-page segments so each page gets its own border + accent
    bar, instead of one bogus rectangle from y_start on page N to y_end on
    page N+1.

    `page_start` / `page_end` default to the current page (single-page card).
    """
    cur = pdf.page_no()
    p0 = page_start if page_start is not None else cur
    p1 = page_end if page_end is not None else cur

    if p0 == p1:
        _draw_card_segment(
            pdf, p0, y_start, y_end,
            fill=fill, border=border, accent=accent, accent_w=accent_w,
        )
        return

    # Multi-page span: top of first page, all of intermediates, bottom of last.
    bottom_y = PAGE_H_PT - M_BOTTOM
    top_y = M_TOP
    _draw_card_segment(
        pdf, p0, y_start, bottom_y,
        fill=fill, border=border, accent=accent, accent_w=accent_w,
    )
    for p in range(p0 + 1, p1):
        _draw_card_segment(
            pdf, p, top_y, bottom_y,
            fill=fill, border=border, accent=accent, accent_w=accent_w,
        )
    _draw_card_segment(
        pdf, p1, top_y, y_end,
        fill=fill, border=border, accent=accent, accent_w=accent_w,
    )


def _bullet_line(
    pdf: FPDF,
    text: str,
    *,
    size: float = 10,
    color: tuple[int, int, int] = (30, 30, 30),
    indent: float = 0,
    right_pad: float = 0,
    bullet_w: float = 10,
    line_height: float = 1.4,
) -> None:
    """Render a bulleted line with a hanging indent.

    A naive multi_cell prepended with `\u2022 ` wraps continuation lines back
    to the bullet glyph, which looks ugly. Here we render the bullet glyph in
    a fixed-width cell, then render the body text with multi_cell starting
    after the glyph — wrapped lines align to the body, not the bullet.
    """
    pdf.set_font("Helvetica", size=size)
    pdf.set_text_color(*color)
    h = size * line_height
    x = M_LEFT + indent
    y = pdf.get_y()
    # Bullet glyph in a fixed-width column.
    pdf.set_xy(x, y)
    pdf.cell(w=bullet_w, h=h, txt="\u2022", align="L")
    # Body — multi_cell, starting where the bullet ended, hanging indent.
    pdf.set_xy(x + bullet_w, y)
    pdf.multi_cell(
        w=CONTENT_W - indent - bullet_w - right_pad,
        h=h,
        txt=_safe_text(str(text or "")),
        new_x="LMARGIN",
        new_y="NEXT",
    )


def _ensure_room(pdf: FPDF, needed: float) -> None:
    """Force a page break if `needed` points won't fit below the current y.

    Used to avoid rendering a card with only a header at the bottom of a
    page and the rest of its body wrapping to the next page.
    """
    if pdf.get_y() + needed > PAGE_H_PT - M_BOTTOM:
        pdf.add_page()


def _measure_text_height(
    pdf: FPDF,
    text: str,
    *,
    size: float,
    style: str = "",
    indent: float = 0,
    right_pad: float = 0,
    line_height: float = 1.4,
) -> float:
    """Measure the rendered height of a wrapped text block without drawing it.

    Uses fpdf2's `split_only=True` to get the wrapped line list, then
    multiplies by line height. Lets us pre-compute card heights and force
    a clean page break before a card that wouldn't fit.
    """
    pdf.set_font("Helvetica", style=style, size=size)
    h = size * line_height
    w = CONTENT_W - indent - right_pad
    safe = _safe_text(str(text or ""))
    if not safe:
        return h  # one empty line still occupies vertical space
    try:
        lines = pdf.multi_cell(w=w, h=h, txt=safe, split_only=True)
    except TypeError:
        # Older fpdf2 builds — best-effort fallback by character count.
        avg_char_w = size * 0.5
        chars_per_line = max(1, int(w / avg_char_w))
        lines = [safe[i:i + chars_per_line] for i in range(0, len(safe), chars_per_line)] or [""]
    return max(1, len(lines)) * h


def _measure_finding_card_height(
    pdf: FPDF,
    f: dict,
    *,
    pad_l: float,
    pad_r: float,
) -> float:
    """Pre-compute the rendered height of a finding card.

    Mirrors the layout in the rendering loop exactly — keep these in sync
    when changing visuals.
    """
    h = 0.0
    h += 8                                       # top padding
    h += 10                                      # severity · status tag (8.5pt × 1 line)
    h += 2                                       # gap after tag
    h += _measure_text_height(
        pdf, f.get("requirement", ""),
        size=11, style="B", indent=pad_l, right_pad=pad_r,
    )
    h += 2                                       # gap after title
    h += _measure_text_height(
        pdf, f"Regulation: {f.get('regulation','')}",
        size=9, style="I", indent=pad_l, right_pad=pad_r,
    )
    requires = f.get("requires") or []
    if requires:
        h += _measure_text_height(
            pdf, f"Required documents: {', '.join(requires)}",
            size=9, indent=pad_l, right_pad=pad_r,
        )
        matched = f.get("matched") or []
        h += _measure_text_height(
            pdf,
            f"Documents on file: {', '.join(matched) if matched else '(none)'}",
            size=9, indent=pad_l, right_pad=pad_r,
        )
    else:
        h += _measure_text_height(
            pdf,
            "Process control \u2014 not evidenced by submitted documents.",
            size=9, indent=pad_l, right_pad=pad_r,
        )
    h += 4                                       # gap before details
    h += _measure_text_height(
        pdf, f.get("details", ""),
        size=10, indent=pad_l, right_pad=pad_r,
    )
    h += 3                                       # gap before remediation
    h += _measure_text_height(
        pdf, f"Remediation: {f.get('remediation','')}",
        size=10, style="I", indent=pad_l, right_pad=pad_r,
    )
    h += 6                                       # bottom padding
    return h


def _sort_key(f: dict) -> tuple[int, int, str]:
    return (
        _SEVERITY_ORDER.get(f.get("severity", ""), 9),
        _STATUS_WEIGHT.get(f.get("status", ""), 9),
        f.get("id", ""),
    )


def build_compliance_report_pdf(
    *,
    package_name: str,
    borrower_name: str | None,
    loan_reference: str | None,
    loan_context: dict,
    findings: list[dict],
    summary: dict,
    rules_version: str,
    rule_set_hash: str,
    report_date: date | None = None,
) -> bytes:
    """Render the report and return PDF bytes."""
    pdf = _setup_pdf()
    today = (report_date or date.today()).isoformat()
    program = loan_context.get("program", "—")
    purpose = loan_context.get("purpose", "—")
    state = loan_context.get("state", "—")

    # Logikality logo (right-aligned) ------------------------------------
    # Mirrors the TI report layout so customers see the same brand mark on
    # every report PDF. Logo height fixed at ~12pt to match the title-block
    # cap height; if the asset is missing we silently skip.
    logo_path = _find_logikality_logo()
    if logo_path:
        logo_h = 24.0
        pdf.image(
            logo_path,
            x=PAGE_W_PT - M_RIGHT - 80,
            y=pdf.get_y(),
            h=logo_h,
        )
        # Reserve vertical space so the title doesn't crash into the logo.
        pdf.ln(logo_h + 4)

    # Title block --------------------------------------------------------
    _write_text(
        pdf,
        f"Compliance Report — {loan_reference or package_name}",
        size=22, style="B", color=_BRAND_CHARCOAL, after=2,
    )
    # Thin amber accent rule under the title.
    pdf.set_draw_color(*_BRAND_AMBER)
    pdf.set_line_width(1.2)
    y = pdf.get_y()
    pdf.line(M_LEFT, y, M_LEFT + 80, y)
    pdf.set_line_width(0.6)
    pdf.ln(10)

    # Meta card — subtle bordered card with amber left accent.
    meta_page_start = pdf.page_no()
    meta_y_start = pdf.get_y()
    pdf.ln(6)  # top padding inside card
    _write_text(pdf, f"Prepared: {today}", size=10, color=_MUTED, indent=14, right_pad=14)
    if borrower_name:
        _write_text(pdf, f"Borrower: {borrower_name}", size=10, color=_MUTED, indent=14, right_pad=14)
    _write_text(pdf, f"Program: {program}", size=10, color=_MUTED, indent=14, right_pad=14)
    _write_text(pdf, f"Loan purpose: {purpose}", size=10, color=_MUTED, indent=14, right_pad=14)
    _write_text(pdf, f"Subject state: {state}", size=10, color=_MUTED, indent=14, right_pad=14)
    pdf.ln(4)  # bottom padding
    meta_y_end = pdf.get_y()
    meta_page_end = pdf.page_no()
    _draw_card(
        pdf, meta_y_start, meta_y_end,
        page_start=meta_page_start, page_end=meta_page_end,
        fill=None, border=_BORDER, accent=_BRAND_AMBER,
    )
    pdf.ln(12)

    # Executive summary --------------------------------------------------
    _write_text(pdf, "Executive Summary", size=14, style="B", color=_BRAND_CHARCOAL, after=4)

    summary_page_start = pdf.page_no()
    summary_y_start = pdf.get_y()
    pdf.ln(6)
    _write_text(pdf, f"Total checks: {summary.get('total', 0)}", size=10, color=_BODY, indent=14, right_pad=14)
    _write_text(
        pdf, f"Compliant: {summary.get('compliant', 0)}",
        size=10, color=_STATUS_COLORS["compliant"], indent=14, right_pad=14,
    )
    _write_text(
        pdf, f"Partial: {summary.get('partial', 0)}",
        size=10, color=_STATUS_COLORS["partial"], indent=14, right_pad=14,
    )
    _write_text(
        pdf, f"Missing: {summary.get('missing', 0)}",
        size=10, color=_STATUS_COLORS["missing"], indent=14, right_pad=14,
    )
    _write_text(
        pdf,
        f"Attestation required (out-of-document): {summary.get('attestation_required', 0)}",
        size=10, color=_STATUS_COLORS["attestation_required"], indent=14, right_pad=14,
    )
    open_criticals = summary.get("open_criticals") or []
    _write_text(
        pdf, f"Open critical findings: {len(open_criticals)}",
        size=10, style="B", color=_SEVERITY_COLORS["critical"], indent=14, right_pad=14,
    )
    pdf.ln(4)
    summary_y_end = pdf.get_y()
    summary_page_end = pdf.page_no()
    _draw_card(
        pdf, summary_y_start, summary_y_end,
        page_start=summary_page_start, page_end=summary_page_end,
        fill=None, border=_BORDER, accent=_BRAND_CHARCOAL,
    )
    pdf.ln(10)

    if open_criticals:
        # Red-bordered callout card.
        crit_page_start = pdf.page_no()
        crit_y_start = pdf.get_y()
        pdf.ln(6)
        _write_text(
            pdf,
            "Critical findings requiring resolution before closing",
            size=11, style="B", color=_SEVERITY_COLORS["critical"],
            indent=14, right_pad=14, after=4,
        )
        for i, f in enumerate(open_criticals):
            if i > 0:
                pdf.ln(3)  # breathing room between bullets
            _bullet_line(
                pdf,
                f"{f.get('requirement','')} \u2014 {f.get('regulation','')}",
                size=10, color=_BODY, indent=18, right_pad=14, bullet_w=10,
            )
        pdf.ln(4)
        crit_y_end = pdf.get_y()
        crit_page_end = pdf.page_no()
        _draw_card(
            pdf, crit_y_start, crit_y_end,
            page_start=crit_page_start, page_end=crit_page_end,
            fill=None, border=_SEVERITY_COLORS["critical"],
            accent=_SEVERITY_COLORS["critical"], accent_w=3,
        )
        pdf.ln(12)
    else:
        pdf.ln(4)

    _hr(pdf)

    # Findings by category ----------------------------------------------
    ordered = sorted(findings, key=_sort_key)
    by_category: dict[str, list[dict]] = {}
    for f in ordered:
        by_category.setdefault(f.get("category", "Uncategorized"), []).append(f)

    pad_l = 14.0
    pad_r = 14.0
    page_avail = PAGE_H_PT - M_TOP - M_BOTTOM  # max card height that can fit a single page

    # Keep the master "Findings by Category" heading glued to its first
    # category and first finding so it never lands orphaned at the bottom.
    if findings:
        first_cat_first_finding = ordered[0]
        first_card_h = _measure_finding_card_height(
            pdf, first_cat_first_finding, pad_l=pad_l, pad_r=pad_r,
        )
        # Master heading (~20pt) + category sub-header (~22pt) + first card.
        _ensure_room(pdf, 20 + 22 + min(first_card_h, page_avail))

    _write_text(pdf, "Findings by Category", size=14, style="B", color=_BRAND_CHARCOAL, after=6)

    for cat, group in by_category.items():
        # Keep the category header glued to its first finding: ensure enough
        # room for the header + the first finding card.
        if group:
            first_h = _measure_finding_card_height(pdf, group[0], pad_l=pad_l, pad_r=pad_r)
            # 14pt header text + 8pt rule/gap + first card + 10pt gap.
            _ensure_room(pdf, 14 + 8 + min(first_h, page_avail) + 10)

        # Category sub-header with amber underline rule.
        _write_text(pdf, cat, size=12, style="B", color=_BRAND_CHARCOAL, after=0)
        pdf.set_draw_color(*_BRAND_AMBER)
        pdf.set_line_width(0.8)
        y = pdf.get_y() + 1
        pdf.line(M_LEFT, y, M_LEFT + 70, y)
        pdf.set_line_width(0.6)
        pdf.ln(6)

        for f in group:
            sev_key = (f.get("severity") or "low").lower()
            sev_color = _SEVERITY_COLORS.get(sev_key, _SEVERITY_COLORS["low"])
            status_key = f.get("status", "")
            status_color = _STATUS_COLORS.get(status_key, _MUTED)
            status_label = _STATUS_LABEL.get(status_key, status_key).upper()

            # ── BEGIN finding card ──
            # Pre-measure card height. If it fits on a single page, force a
            # break when remaining space is insufficient. If a single card is
            # taller than a full page (rare), just let the multi-page card
            # drawing handle it.
            card_h = _measure_finding_card_height(pdf, f, pad_l=pad_l, pad_r=pad_r)
            if card_h <= page_avail:
                _ensure_room(pdf, card_h)
            f_page_start = pdf.page_no()
            f_y_start = pdf.get_y()
            pdf.ln(8)  # top padding

            # Top line: small severity · status tag (uppercase, tracked).
            # Single multi_cell with one color group per segment via two cells
            # on the same line, but no width-stitching gymnastics — just a
            # plain single-line tag in severity color, with status appended
            # in the same color so spacing is consistent.
            pdf.set_font("Helvetica", style="B", size=8.5)
            pdf.set_text_color(*sev_color)
            pdf.set_x(M_LEFT + pad_l)
            pdf.cell(
                w=CONTENT_W - pad_l - pad_r,
                h=10,
                txt=_safe_text(f"{sev_key.upper()}  \u00b7  {status_label}"),
                new_x="LMARGIN",
                new_y="NEXT",
            )
            pdf.ln(2)

            # Requirement title — charcoal, bold, 11pt.
            _write_text(
                pdf, f.get("requirement", ""),
                size=11, style="B", color=_BRAND_CHARCOAL,
                indent=pad_l, right_pad=pad_r, after=2,
            )

            # Regulation — magenta italic citation.
            _write_text(
                pdf, f"Regulation: {f.get('regulation','')}",
                size=9, style="I", color=_BRAND_MAGENTA,
                indent=pad_l, right_pad=pad_r,
            )

            requires = f.get("requires") or []
            if requires:
                _write_text(
                    pdf, f"Required documents: {', '.join(requires)}",
                    size=9, color=_MUTED, indent=pad_l, right_pad=pad_r,
                )
                matched = f.get("matched") or []
                _write_text(
                    pdf,
                    f"Documents on file: {', '.join(matched) if matched else '(none)'}",
                    size=9, color=_MUTED, indent=pad_l, right_pad=pad_r,
                )
            else:
                _write_text(
                    pdf,
                    "Process control \u2014 not evidenced by submitted documents.",
                    size=9, color=_MUTED, indent=pad_l, right_pad=pad_r,
                )

            pdf.ln(4)
            _write_text(
                pdf, f.get("details", ""),
                size=10, color=_BODY, indent=pad_l, right_pad=pad_r,
            )
            pdf.ln(3)
            _write_text(
                pdf, f"Remediation: {f.get('remediation','')}",
                size=10, style="I", color=_BRAND_PURPLE,
                indent=pad_l, right_pad=pad_r,
            )
            pdf.ln(6)  # bottom padding

            f_y_end = pdf.get_y()
            f_page_end = pdf.page_no()
            _draw_card(
                pdf, f_y_start, f_y_end,
                page_start=f_page_start, page_end=f_page_end,
                fill=None, border=_BORDER, accent=sev_color, accent_w=3,
            )
            pdf.ln(10)  # gap between finding cards
        pdf.ln(4)

    # Footer disclaimer + version stamp ----------------------------------
    pdf.ln(12)
    # Magenta accent line — matches TI footer treatment.
    pdf.set_draw_color(*_BRAND_MAGENTA)
    pdf.set_line_width(1.0)
    y = pdf.get_y()
    pdf.line(M_LEFT, y, PAGE_W_PT - M_RIGHT, y)
    pdf.set_line_width(0.6)
    pdf.ln(6)
    _write_text(
        pdf,
        (
            "This report is generated from the document classification of the submitted "
            "package. Items flagged as 'Attestation required' cover process controls "
            "(CIP/OFAC, flood determination, GLBA notices) that do not produce a "
            "borrower-side document and must be evidenced from LOS attestations or "
            "compliance system logs. This is a desk-level audit aid, not a substitute "
            "for legal counsel or formal compliance review."
        ),
        size=8, style="I", color=_MUTED, after=4,
    )
    _write_text(
        pdf,
        f"Engine: {rules_version} \u00b7 rule_set_hash: {rule_set_hash[:16]}\u2026",
        size=7, color=_SUBTLE,
    )

    out = pdf.output(dest="S")
    if isinstance(out, str):
        # fpdf2 returns str on some versions; normalize to bytes.
        return out.encode("latin-1")
    return bytes(out)
