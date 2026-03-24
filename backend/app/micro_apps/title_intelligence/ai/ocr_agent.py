"""OCR agent using Claude Vision API via litellm.

Replaces Tesseract with cloud-based vision OCR for production performance.
Falls back to Tesseract if ANTHROPIC_API_KEY is not set.
"""

import base64
import io
import logging

import pytesseract
from PIL import Image

from app.config import get_settings

logger = logging.getLogger(__name__)


class OCRAgent:
    """Extract text from page images using Claude Vision or Tesseract fallback."""

    def __init__(self):
        settings = get_settings()
        self.use_vision = bool(settings.ANTHROPIC_API_KEY)
        if settings.TESSERACT_PATH:
            pytesseract.pytesseract.tesseract_cmd = settings.TESSERACT_PATH

    async def extract_text_async(self, image_data: bytes) -> dict:
        """Extract text from a page image using Claude Vision API.

        This is an async call that sends the image to Claude for OCR.

        Returns: {"text": str, "confidence": float}
        """
        if not self.use_vision:
            # Fallback to Tesseract for environments without API key (e.g., tests)
            return self.extract_text(image_data)

        import litellm
        from app.ai.base_service import _ensure_configured, PLATFORM_MODELS

        _ensure_configured()

        settings = get_settings()
        platform = settings.AI_PLATFORM
        models = PLATFORM_MODELS.get(platform, PLATFORM_MODELS["anthropic"])
        model = models["default"]

        # Encode image as base64
        b64_image = base64.b64encode(image_data).decode("utf-8")

        # Detect media type
        media_type = "image/jpeg"
        if image_data[:4] == b"\x89PNG":
            media_type = "image/png"

        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{media_type};base64,{b64_image}",
                        },
                    },
                    {
                        "type": "text",
                        "text": "Extract ALL text from this document page exactly as written. Preserve line breaks and formatting. Return ONLY the extracted text, nothing else.",
                    },
                ],
            }
        ]

        try:
            response = await litellm.acompletion(
                model=model,
                messages=messages,
                max_tokens=4096,
                temperature=0.0,
            )
            text = response.choices[0].message.content or ""
            return {
                "text": text.strip(),
                "confidence": 1.0 if text.strip() else 0.0,
            }
        except Exception as e:
            logger.warning(f"Vision OCR failed, falling back to Tesseract: {e}")
            return self.extract_text(image_data)

    def extract_text(self, image_data: bytes) -> dict:
        """Extract text from a page image using Tesseract (sync fallback).

        Returns: {"text": str, "confidence": float}
        """
        image = Image.open(io.BytesIO(image_data))

        # Convert to grayscale — 66% less data for Tesseract to process
        if image.mode != "L":
            image = image.convert("L")

        # --oem 1: LSTM only (faster than default LSTM+Legacy)
        # --psm 6: Assume single uniform text block (skip page segmentation)
        text = pytesseract.image_to_string(image, lang="eng", config="--oem 1 --psm 6")

        return {
            "text": text.strip(),
            "confidence": 1.0 if text.strip() else 0.0,
        }
