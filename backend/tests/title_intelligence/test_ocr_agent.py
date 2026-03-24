"""Tests for Tesseract OCR agent."""

import pytest
from unittest.mock import patch, MagicMock
from io import BytesIO
from PIL import Image

from app.micro_apps.title_intelligence.ai.ocr_agent import OCRAgent


def _create_test_image(text: str = "Hello World") -> bytes:
    """Create a simple test image with text."""
    img = Image.new("RGB", (200, 50), color="white")
    buf = BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


@patch("app.micro_apps.title_intelligence.ai.ocr_agent.pytesseract")
@patch("app.micro_apps.title_intelligence.ai.ocr_agent.get_settings")
def test_extract_text(mock_settings, mock_tesseract):
    """OCR agent extracts text from image using Tesseract."""
    mock_settings.return_value = MagicMock(TESSERACT_PATH="")

    mock_tesseract.image_to_string.return_value = "Schedule A\nEffective Date: 2024-01-15"

    agent = OCRAgent()
    result = agent.extract_text(_create_test_image())

    assert "text" in result
    assert "confidence" in result
    assert result["text"] == "Schedule A\nEffective Date: 2024-01-15"
    assert result["confidence"] == 1.0
    mock_tesseract.image_to_string.assert_called_once()


@patch("app.micro_apps.title_intelligence.ai.ocr_agent.pytesseract")
@patch("app.micro_apps.title_intelligence.ai.ocr_agent.get_settings")
def test_extract_text_empty(mock_settings, mock_tesseract):
    """OCR agent handles pages with no text."""
    mock_settings.return_value = MagicMock(TESSERACT_PATH="")

    mock_tesseract.image_to_string.return_value = ""

    agent = OCRAgent()
    result = agent.extract_text(_create_test_image())

    assert result["text"] == ""
    assert result["confidence"] == 0.0


@patch("app.micro_apps.title_intelligence.ai.ocr_agent.pytesseract")
@patch("app.micro_apps.title_intelligence.ai.ocr_agent.get_settings")
def test_custom_tesseract_path(mock_settings, mock_tesseract):
    """OCR agent uses custom tesseract path when configured."""
    mock_settings.return_value = MagicMock(TESSERACT_PATH="/usr/local/bin/tesseract")
    mock_tesseract.pytesseract = MagicMock()

    agent = OCRAgent()
    assert mock_tesseract.pytesseract.tesseract_cmd == "/usr/local/bin/tesseract"


@patch("app.micro_apps.title_intelligence.ai.ocr_agent.pytesseract")
@patch("app.micro_apps.title_intelligence.ai.ocr_agent.get_settings")
def test_no_base_ai_service(mock_settings, mock_tesseract):
    """OCR agent is a plain utility, not a BaseAIService subclass."""
    mock_settings.return_value = MagicMock(TESSERACT_PATH="")
    from app.ai.base_service import BaseAIService
    agent = OCRAgent()
    assert not isinstance(agent, BaseAIService)
