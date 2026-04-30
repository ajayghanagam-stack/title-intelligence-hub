"""Build the reorganized "final packet" PDF (or per-stack ZIP) for a loan package.

Pages are emitted in stack order (`stack_index` ascending) and within each
stack in `page_numbers` order — i.e. exactly the layout the reviewer sees in
the dashboard after applying any "Move to…" overrides. Each stack starts a
new top-level bookmark labeled with its doc-type and page span so the
downstream consumer (lender/QC) can navigate the assembled PDF directly.

The functions are pure I/O over PyMuPDF + storage; no LLM calls. They are
safe to re-run after every override because they always reflect the current
`lo_stacks` / `lo_pages` state.
"""
from __future__ import annotations

import io
import logging
import re
import uuid
import zipfile
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.micro_apps.loan_onboarding.models.package_file import LOPackageFile
from app.micro_apps.loan_onboarding.models.page import LOPage
from app.micro_apps.loan_onboarding.models.stack import LOStack
from app.services.storage import StorageProvider

logger = logging.getLogger(__name__)


def _stack_label(doc_type: str, first_page: int, last_page: int) -> str:
    """Human-friendly bookmark label, e.g. "Paystub (pp. 4–7)"."""
    span = (
        f"p. {first_page}"
        if first_page == last_page
        else f"pp. {first_page}\u2013{last_page}"
    )
    return f"{doc_type} ({span})"


def _slugify(value: str) -> str:
    """Filename-safe ASCII slug for ZIP entries."""
    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").lower()
    return cleaned or "stack"


async def _load_package_assets(
    db: AsyncSession,
    org_id: uuid.UUID,
    package_id: uuid.UUID,
    storage: StorageProvider,
):
    """Fetch stacks + pages + source PDFs for a package.

    Returns `(stacks, pages_by_number, load_pdf)` where `load_pdf` is an
    async callable that lazily fetches and caches a source PDF by file_id.
    Caller is responsible for closing every cached PDF when done.
    """
    import fitz  # PyMuPDF — local import keeps app boot light

    stacks_q = (
        select(LOStack)
        .where(LOStack.package_id == package_id, LOStack.org_id == org_id)
        .order_by(LOStack.stack_index.asc())
    )
    stacks: list[LOStack] = list((await db.execute(stacks_q)).scalars().all())

    pages_q = (
        select(LOPage)
        .where(LOPage.package_id == package_id, LOPage.org_id == org_id)
        .order_by(LOPage.page_number.asc())
    )
    pages: list[LOPage] = list((await db.execute(pages_q)).scalars().all())
    pages_by_number: dict[int, LOPage] = {p.page_number: p for p in pages}

    file_ids: set[uuid.UUID] = {p.file_id for p in pages}
    files_by_id: dict[uuid.UUID, LOPackageFile] = {}
    if file_ids:
        files_q = select(LOPackageFile).where(
            LOPackageFile.id.in_(file_ids), LOPackageFile.org_id == org_id
        )
        for f in (await db.execute(files_q)).scalars().all():
            files_by_id[f.id] = f

    pdf_cache: dict[uuid.UUID, fitz.Document] = {}

    async def load_pdf(file_id: uuid.UUID) -> fitz.Document | None:
        if file_id in pdf_cache:
            return pdf_cache[file_id]
        file_row = files_by_id.get(file_id)
        if file_row is None:
            return None
        try:
            data = await storage.get_object(file_row.storage_path)
        except Exception:
            logger.exception(
                "final_packet: failed to load source PDF %s", file_row.storage_path
            )
            return None
        doc = fitz.open(stream=data, filetype="pdf")
        pdf_cache[file_id] = doc
        return doc

    return stacks, pages_by_number, load_pdf, pdf_cache


async def build_final_packet_pdf(
    db: AsyncSession,
    org_id: uuid.UUID,
    package_id: uuid.UUID,
    storage: StorageProvider,
) -> bytes:
    """Assemble the reorganized PDF and return its bytes.

    Returns an empty PDF (single blank page with a "no pages" notice) if the
    package has no stacks yet — this should not happen post-pipeline but
    keeps the route safe for half-processed packages.
    """
    import fitz  # PyMuPDF — local import keeps app boot light

    stacks, pages_by_number, load_pdf, pdf_cache = await _load_package_assets(
        db, org_id, package_id, storage
    )

    out_doc = fitz.open()
    toc: list[list] = []  # PyMuPDF TOC: [level, title, page_number, ...]

    try:
        for stack in stacks:
            stack_start_out_page = out_doc.page_count + 1  # 1-indexed for TOC
            page_numbers: Iterable[int] = stack.page_numbers or []
            for global_pn in page_numbers:
                page = pages_by_number.get(global_pn)
                if page is None:
                    continue
                src = await load_pdf(page.file_id)
                if src is None:
                    continue
                src_idx = max(0, min(page.source_page_number - 1, src.page_count - 1))
                # insert_pdf copies pages losslessly (preserves text, vectors,
                # fonts) — no re-rastering.
                out_doc.insert_pdf(src, from_page=src_idx, to_page=src_idx)

            # Only emit a bookmark if at least one page actually landed.
            if out_doc.page_count >= stack_start_out_page:
                toc.append(
                    [
                        1,
                        _stack_label(
                            stack.doc_type, stack.first_page, stack.last_page
                        ),
                        stack_start_out_page,
                    ]
                )

        if out_doc.page_count == 0:
            # Edge case: no stacks (or all source files missing). Emit a
            # single placeholder page so the response is still a valid PDF.
            placeholder = out_doc.new_page(width=612, height=792)
            placeholder.insert_text(
                (72, 120),
                "No pages available for this package.",
                fontsize=14,
            )
        else:
            out_doc.set_toc(toc)

        buf = io.BytesIO()
        out_doc.save(buf, garbage=3, deflate=True)
        return buf.getvalue()
    finally:
        for doc in pdf_cache.values():
            try:
                doc.close()
            except Exception:
                pass
        try:
            out_doc.close()
        except Exception:
            pass


async def build_per_stack_zip(
    db: AsyncSession,
    org_id: uuid.UUID,
    package_id: uuid.UUID,
    storage: StorageProvider,
) -> bytes:
    """Assemble one PDF per stack and return them bundled in a ZIP.

    Filenames follow the pattern `{stack_index:02d}-{doc-slug}-pp{first}-{last}.pdf`
    so they sort naturally in any file browser. Stacks that resolve to zero
    pages (e.g. all source files missing) are skipped silently.
    """
    import fitz  # PyMuPDF

    stacks, pages_by_number, load_pdf, pdf_cache = await _load_package_assets(
        db, org_id, package_id, storage
    )

    zip_buf = io.BytesIO()
    try:
        with zipfile.ZipFile(
            zip_buf, mode="w", compression=zipfile.ZIP_DEFLATED
        ) as zf:
            for stack in stacks:
                stack_doc = fitz.open()
                try:
                    page_numbers: Iterable[int] = stack.page_numbers or []
                    for global_pn in page_numbers:
                        page = pages_by_number.get(global_pn)
                        if page is None:
                            continue
                        src = await load_pdf(page.file_id)
                        if src is None:
                            continue
                        src_idx = max(
                            0, min(page.source_page_number - 1, src.page_count - 1)
                        )
                        stack_doc.insert_pdf(
                            src, from_page=src_idx, to_page=src_idx
                        )

                    if stack_doc.page_count == 0:
                        continue

                    span = (
                        f"p{stack.first_page}"
                        if stack.first_page == stack.last_page
                        else f"pp{stack.first_page}-{stack.last_page}"
                    )
                    name = (
                        f"{stack.stack_index + 1:02d}-"
                        f"{_slugify(stack.doc_type)}-{span}.pdf"
                    )
                    pdf_buf = io.BytesIO()
                    stack_doc.save(pdf_buf, garbage=3, deflate=True)
                    zf.writestr(name, pdf_buf.getvalue())
                finally:
                    try:
                        stack_doc.close()
                    except Exception:
                        pass

            # If no stacks produced any PDF, drop a README so the ZIP isn't
            # an empty archive (some unzip tools error on empty zips).
            if not zf.namelist():
                zf.writestr(
                    "README.txt",
                    "No stacks available for this package yet.\n",
                )

        return zip_buf.getvalue()
    finally:
        for doc in pdf_cache.values():
            try:
                doc.close()
            except Exception:
                pass
