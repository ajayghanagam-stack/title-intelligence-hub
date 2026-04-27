"""Classification Schema — matches the brief verbatim.

{
  "page_number": "integer",
  "predicted_doc_type": "string | enum from config",
  "predicted_doc_type_alternatives": [{"type": "string", "confidence": "float"}],
  "confidence": "float 0-1",
  "page_role": "first_page | continuation | last_page | signature_page | unknown",
  "detected_fields": [{"field_name": "string", "value": "string", "bbox": [x1,y1,x2,y2]}]
}
"""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


PageRole = Literal["first_page", "continuation", "last_page", "signature_page", "unknown"]


class ClassificationAlternative(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: str
    confidence: float = Field(ge=0.0, le=1.0)


class DetectedField(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field_name: str
    value: str
    # [x1, y1, x2, y2] — pixel coordinates, normalized 0-1 if bbox_normalized=True upstream
    bbox: list[float] = Field(min_length=4, max_length=4)


class Classification(BaseModel):
    """Single-page classification output."""
    model_config = ConfigDict(extra="forbid")

    page_number: int = Field(ge=1)
    predicted_doc_type: str
    predicted_doc_type_alternatives: list[ClassificationAlternative] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    page_role: PageRole = "unknown"
    detected_fields: list[DetectedField] = Field(default_factory=list)


class ClassificationBatchResult(BaseModel):
    """Output of a batched classification call for multiple pages."""
    model_config = ConfigDict(extra="forbid")
    classifications: list[Classification]
