from fastapi import APIRouter

from app.micro_apps.base import MicroAppBase
from app.micro_apps.loan_onboarding.routes import get_lo_router


class LoanOnboardingMicroApp(MicroAppBase):
    @property
    def slug(self) -> str:
        return "loan-onboarding"

    @property
    def name(self) -> str:
        return "Loan Onboarding"

    @property
    def description(self) -> str:
        return (
            "Split, classify, and validate mortgage loan packages with configurable "
            "document types, validation rules, and human-in-the-loop review."
        )

    @property
    def icon(self) -> str:
        return "folder-open"

    def get_router(self) -> APIRouter:
        return get_lo_router()

    def get_models(self) -> list[type]:
        from app.micro_apps.loan_onboarding.models import (
            LOPackage,
            LOPackageFile,
            LOPage,
            LODocTypeConfig,
            LOClassification,
            LOStack,
            LOValidationRule,
            LOValidationResult,
            LOHITLReview,
            LOPipelineRun,
            LOPageOverride,
        )
        return [
            LOPackage,
            LOPackageFile,
            LOPage,
            LODocTypeConfig,
            LOClassification,
            LOStack,
            LOValidationRule,
            LOValidationResult,
            LOHITLReview,
            LOPipelineRun,
            LOPageOverride,
        ]


micro_app = LoanOnboardingMicroApp()
