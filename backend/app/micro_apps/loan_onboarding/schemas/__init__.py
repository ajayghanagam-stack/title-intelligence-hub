"""Pydantic schemas for Loan Onboarding micro-app.

Classification and Validation schemas match the user's brief verbatim.
"""
from app.micro_apps.loan_onboarding.schemas.classification import (
    Classification,
    ClassificationAlternative,
    DetectedField,
    PageRole,
    ClassificationBatchResult,
)
from app.micro_apps.loan_onboarding.schemas.validation import (
    RuleEvaluation,
    RuleLocation,
    ConfidenceBreakdown,
    ValidationResult,
)
from app.micro_apps.loan_onboarding.schemas.package import (
    DocTypeSpec,
    ValidationRuleSpec,
    PackageCreate,
    PackageResponse,
    PackageListResponse,
    PipelineStatusResponse,
    ProgressSnapshot,
)
from app.micro_apps.loan_onboarding.schemas.review import (
    HITLDecision,
    HITLReviewResponse,
    ReviewQueueItem,
)

__all__ = [
    "Classification",
    "ClassificationAlternative",
    "DetectedField",
    "PageRole",
    "ClassificationBatchResult",
    "RuleEvaluation",
    "RuleLocation",
    "ConfidenceBreakdown",
    "ValidationResult",
    "DocTypeSpec",
    "ValidationRuleSpec",
    "PackageCreate",
    "PackageResponse",
    "PackageListResponse",
    "PipelineStatusResponse",
    "ProgressSnapshot",
    "HITLDecision",
    "HITLReviewResponse",
    "ReviewQueueItem",
]
