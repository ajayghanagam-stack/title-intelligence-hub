"""Per-page OCR producing the Phase 1 ``OcrWord[]`` payload.

The vision-grounded extractor consumes a token table — list of
``{index, text, bbox, line, confidence}`` per page — alongside the page
image. Bboxes are normalized to 0..1 so re-renders at different DPI
produce stable indices. This service is the single source of truth for
producing that payload; it lives outside any route so the ingest
pipeline + per-page workbench OCR endpoint share the same code path.

Engines:
  - **Primary**: Tesseract via ``pytesseract.image_to_data``. Fast (~600
    ms / page), runs locally, gives word-level bboxes + confidences.
  - **Fallback**: Gemini Vision (D7 in docs/phase0/README.md). Triggered
    when the Tesseract median word confidence < ``MIN_TESSERACT_CONF``
    or Tesseract returns zero words. Adds ~2 s / page on the fallback
    path.

Output is a tuple ``(words, engine)`` where ``engine`` is one of
``"tesseract"`` | ``"gemini_vision"`` | ``""`` (no words extracted).

The result is persisted on ``LOPage.ocr_words`` (JSONB) and
``LOPage.ocr_engine`` (str) at ingest time. Re-runs of the extract stage
read these columns instead of re-running OCR.
"""
from __future__ import annotations

import asyncio
import io
import logging
from typing import TypedDict

logger = logging.getLogger(__name__)


# ── Constants (Phase 1) ──────────────────────────────────────────────


# DPI used when rendering the PDF page for OCR. 200 DPI is the Phase 1
# default — high enough for clean Tesseract on most paystubs / W-2s,
# low enough that the rendered JPEG fits comfortably under Gemini's
# input cap when the fallback fires.
OCR_RENDER_DPI = 200


# Median Tesseract per-word confidence below which we trigger the
# Gemini Vision fallback. 0..100 (Tesseract's native scale, not
# 0..1). 70 is the threshold called out in CLAUDE.md and the Phase 0
# grounding-contract spec.
MIN_TESSERACT_MEDIAN_CONF: float = 70.0


# Hard ceiling on per-page time budget (seconds). Tesseract runs sync
# under ``asyncio.to_thread`` so this becomes a wall-clock cap.
PER_PAGE_TIMEOUT_SECONDS = 12.0


class OcrWordDict(TypedDict):
    """Plain-dict shape persisted to ``LOPage.ocr_words`` JSONB."""

    index: int
    text: str
    bbox: list[float]  # [x1, y1, x2, y2] in 0..1
    line: int
    confidence: float  # 0..1 (re-scaled from Tesseract's 0..100)


# ── Tesseract path ───────────────────────────────────────────────────


def _tesseract_words_sync(image_bytes: bytes) -> list[OcrWordDict]:
    """Run Tesseract on a rendered page image and return ``OcrWordDict[]``.

    Sync — caller must wrap in ``asyncio.to_thread``. Returns an empty
    list on any failure (missing binary, image decode error, …); the
    caller decides whether to escalate to the Gemini fallback.
    """
    try:
        import pytesseract
        from pytesseract import Output
        from PIL import Image
    except ImportError as e:
        logger.warning("OCR primary unavailable (import failed): %s", e)
        return []

    try:
        img = Image.open(io.BytesIO(image_bytes))
    except Exception as e:
        logger.warning("OCR image decode failed: %s", e)
        return []

    img_w = float(img.width) or 1.0
    img_h = float(img.height) or 1.0

    try:
        data = pytesseract.image_to_data(img, output_type=Output.DICT)
    except pytesseract.TesseractNotFoundError as e:
        logger.warning("Tesseract binary not installed: %s", e)
        return []
    except Exception as e:
        logger.warning("Tesseract call failed: %s", e)
        return []

    out: list[OcrWordDict] = []
    n = len(data.get("text", []))
    next_index = 0
    for i in range(n):
        text = (data["text"][i] or "").strip()
        if not text:
            continue
        try:
            left = float(data["left"][i])
            top = float(data["top"][i])
            width = float(data["width"][i])
            height = float(data["height"][i])
            # Tesseract returns confidence as int (0..100), with -1
            # for non-word entries. Drop -1 entries; rescale to 0..1.
            raw_conf = float(data.get("conf", [0])[i])
            line_no = int(data.get("line_num", [0])[i])
        except (TypeError, ValueError, IndexError):
            continue

        if raw_conf < 0:
            # Non-word entry (block / paragraph / line headers). Skip.
            continue

        x1 = max(0.0, min(1.0, left / img_w))
        y1 = max(0.0, min(1.0, top / img_h))
        x2 = max(0.0, min(1.0, (left + width) / img_w))
        y2 = max(0.0, min(1.0, (top + height) / img_h))
        if x2 <= x1 or y2 <= y1:
            continue

        out.append({
            "index": next_index,
            "text": text,
            "bbox": [x1, y1, x2, y2],
            "line": line_no,
            "confidence": max(0.0, min(1.0, raw_conf / 100.0)),
        })
        next_index += 1

    return out


def _median_confidence(words: list[OcrWordDict]) -> float:
    """Median per-word confidence in 0..100 scale (matches the threshold)."""
    if not words:
        return 0.0
    confs = sorted(w["confidence"] for w in words)
    mid = len(confs) // 2
    if len(confs) % 2 == 0:
        median = (confs[mid - 1] + confs[mid]) / 2
    else:
        median = confs[mid]
    return median * 100.0  # rescale back to Tesseract's 0..100 for comparison


# ── Gemini Vision fallback (D7) ──────────────────────────────────────


_GEMINI_OCR_PROMPT = """\
You are an OCR engine. Read every word visible on the page image and
return a strict JSON object with one record per word, in reading order,
matching this schema:

{
  "words": [
    { "index": int (0-indexed),
      "text": str,
      "bbox": [x1, y1, x2, y2] in 0..1 normalized image coords,
      "line": int (0-indexed line group),
      "confidence": float in 0..1 }
  ]
}

Rules:
- One record per visible word. Do not merge phrases.
- bbox coordinates are 0..1 floats relative to the page image (top-left origin).
- Reading order: top-to-bottom, left-to-right.
- ``line`` groups words on the same horizontal text line.
- Skip purely decorative marks. Include numbers, punctuation, dollar signs.
- Do NOT invent words. If the page is blank, return an empty list.
"""


_GEMINI_OCR_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "words": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer", "minimum": 0},
                    "text": {"type": "string", "minLength": 1, "maxLength": 200},
                    "bbox": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 4,
                        "maxItems": 4,
                    },
                    "line": {"type": "integer", "minimum": 0},
                    "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                },
                "required": ["index", "text", "bbox", "line", "confidence"],
            },
        },
    },
    "required": ["words"],
}


async def _gemini_vision_words(image_bytes: bytes, org_id) -> list[OcrWordDict]:
    """Re-OCR a page via Gemini Vision when Tesseract is too noisy.

    Uses the gemini provider regardless of the LO global ``LO_AI_PROVIDER``
    config — this is OCR, not extraction, and Gemini's vision OCR is the
    documented fallback in CLAUDE.md.
    """
    try:
        from app.ai.base_service import BaseAIService

        class _OcrAgent(BaseAIService):
            pass

        agent = _OcrAgent(org_id, role="ocr", provider_override="gemini")
        messages = [{
            "role": "user",
            "content": [
                {"type": "text", "text": "Extract every visible word with its bbox."},
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": _b64(image_bytes),
                    },
                },
            ],
        }]
        raw = await agent.call_json_structured(
            system_prompt=_GEMINI_OCR_PROMPT,
            messages=messages,
            json_schema=_GEMINI_OCR_SCHEMA,
            max_tokens=8192,
            temperature=0.0,
            timeout=int(PER_PAGE_TIMEOUT_SECONDS),
        )
    except Exception as e:
        logger.warning("Gemini Vision OCR fallback failed: %s", e)
        return []

    if not isinstance(raw, dict):
        return []

    raw_words = raw.get("words") or []
    out: list[OcrWordDict] = []
    next_index = 0
    for w in raw_words:
        if not isinstance(w, dict):
            continue
        text = str(w.get("text") or "").strip()
        if not text:
            continue
        bbox = w.get("bbox")
        if not (isinstance(bbox, (list, tuple)) and len(bbox) == 4):
            continue
        try:
            x1, y1, x2, y2 = (max(0.0, min(1.0, float(c))) for c in bbox)
        except (TypeError, ValueError):
            continue
        if x2 <= x1 or y2 <= y1:
            continue
        try:
            line = int(w.get("line", 0))
            conf = max(0.0, min(1.0, float(w.get("confidence", 0.8))))
        except (TypeError, ValueError):
            line, conf = 0, 0.8
        out.append({
            "index": next_index,
            "text": text[:200],
            "bbox": [x1, y1, x2, y2],
            "line": line,
            "confidence": conf,
        })
        next_index += 1
    return out


def _b64(b: bytes) -> str:
    import base64
    return base64.b64encode(b).decode("ascii")


# ── Public entry points ──────────────────────────────────────────────


async def ocr_page_image(
    image_bytes: bytes,
    *,
    org_id,
    allow_fallback: bool = True,
) -> tuple[list[OcrWordDict], str]:
    """OCR one page image and return ``(words, engine)``.

    ``engine`` is ``"tesseract"`` | ``"gemini_vision"`` | ``""``.
    ``allow_fallback=False`` skips the Gemini Vision path (used by
    callers that have already paid the latency budget elsewhere).
    """
    words = await asyncio.to_thread(_tesseract_words_sync, image_bytes)
    median = _median_confidence(words)

    if words and median >= MIN_TESSERACT_MEDIAN_CONF:
        return words, "tesseract"

    if not allow_fallback:
        # Caller opted out — return whatever Tesseract produced (may be
        # empty); ``ocr_engine`` reflects what we actually used.
        return words, ("tesseract" if words else "")

    logger.info(
        "Tesseract median conf=%.1f below %.1f (or zero words); "
        "falling back to Gemini Vision",
        median, MIN_TESSERACT_MEDIAN_CONF,
    )
    fallback_words = await _gemini_vision_words(image_bytes, org_id)
    if fallback_words:
        return fallback_words, "gemini_vision"

    # Both paths failed — return Tesseract's best effort (may be []).
    return words, ("tesseract" if words else "")


async def ocr_pdf_page(
    pdf_bytes: bytes,
    source_page_number: int,
    *,
    org_id,
    dpi: int = OCR_RENDER_DPI,
    allow_fallback: bool = True,
) -> tuple[list[OcrWordDict], str]:
    """Render one page of ``pdf_bytes`` to JPEG and OCR it.

    ``source_page_number`` is 1-indexed within the PDF. Returns
    ``(words, engine)`` per ``ocr_page_image``.
    """
    image_bytes = await asyncio.to_thread(
        _render_pdf_page_to_jpeg, pdf_bytes, source_page_number, dpi
    )
    if not image_bytes:
        return [], ""
    return await ocr_page_image(image_bytes, org_id=org_id, allow_fallback=allow_fallback)


def _render_pdf_page_to_jpeg(pdf_bytes: bytes, source_page_number: int, dpi: int) -> bytes:
    """Render one PDF page to a JPEG byte string. Sync."""
    try:
        import fitz  # PyMuPDF
    except ImportError as e:
        logger.warning("PyMuPDF unavailable: %s", e)
        return b""

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        idx = max(0, min(source_page_number - 1, len(doc) - 1))
        page = doc[idx]
        try:
            pix = page.get_pixmap(dpi=dpi, alpha=False)
        except Exception as e:
            logger.warning("PDF render failed for page %s: %s", source_page_number, e)
            return b""
        try:
            return pix.tobytes("jpeg")
        except Exception as e:
            logger.warning("JPEG encode failed for page %s: %s", source_page_number, e)
            return b""
    finally:
        doc.close()
