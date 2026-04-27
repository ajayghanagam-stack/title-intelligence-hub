"""Validation Schema — matches the brief verbatim.

{
  "stack_id": "string",
  "doc_type": "string",
  "rules_evaluated": [
    {
      "rule_id": "string",
      "rule_source": "preset | custom",
      "passed": "boolean",
      "evidence": "string (quoted from doc, max 200 chars)",
      "location": {"page": "int", "bbox": [x1,y1,x2,y2]}
    }
  ],
  "confidence_breakdown": {
    "classification": "float 0-1",
    "split_accuracy": "float 0-1",
    "validation": "float 0-1"
  },
  "overall_confidence": "float 0-1",
  "requires_hitl": "boolean"
}
"""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


RuleSource = Literal["preset", "custom"]


class RuleLocation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page: int = Field(ge=1)
    bbox: list[float] = Field(min_length=4, max_length=4)


class RuleEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rule_id: str
    rule_source: RuleSource
    passed: bool
    evidence: str = Field(max_length=200)
    location: RuleLocation | None = None


class ConfidenceBreakdown(BaseModel):
    model_config = ConfigDict(extra="forbid")
    classification: float = Field(ge=0.0, le=1.0)
    split_accuracy: float = Field(ge=0.0, le=1.0)
    validation: float = Field(ge=0.0, le=1.0)


class ValidationResult(BaseModel):
    """Per-stack validation output — matches the user's Validation Schema."""
    model_config = ConfigDict(extra="forbid")
    stack_id: str
    doc_type: str
    rules_evaluated: list[RuleEvaluation]
    confidence_breakdown: ConfidenceBreakdown
    overall_confidence: float = Field(ge=0.0, le=1.0)
    requires_hitl: bool
