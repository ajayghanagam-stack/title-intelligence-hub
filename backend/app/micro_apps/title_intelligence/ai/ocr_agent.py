"""OCR agent using Tesseract (matching V2's tesseract.js pattern).

Replaces Claude Vision with pytesseract — free, fast, offline.
No BaseAIService subclass needed; OCR is a plain utility.
"""

import io
import logging

import pytesseract
from PIL import Image

from app.config import get_settings

logger = logging.getLogger(__name__)


class OCRAgent:
    """Extract text from page images using Tesseract OCR."""

    def __init__(self):
        settings = get_settings()
        if settings.TESSERACT_PATH:
            pytesseract.pytesseract.tesseract_cmd = settings.TESSERACT_PATH

    def extract_text(self, image_data: bytes) -> dict:
        """Extract text from a page image using Tesseract.

        This is a synchronous call — wrap with asyncio.to_thread() in async contexts.

        Returns: {"text": str, "confidence": float}
        """
        image = Image.open(io.BytesIO(image_data))

        # Get full text (single Tesseract call — fast)
        text = pytesseract.image_to_string(image)

        return {
            "text": text.strip(),
            "confidence": 1.0 if text.strip() else 0.0,
        }
