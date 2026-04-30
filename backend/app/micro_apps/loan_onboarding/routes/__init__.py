from fastapi import APIRouter


def get_lo_router() -> APIRouter:
    """Compose all Loan Onboarding sub-routers.

    Sub-routers are imported lazily so that missing route files don't prevent
    app registration during scaffolding.
    """
    router = APIRouter(tags=["loan-onboarding"])

    # Sub-routers are added as they're implemented
    try:
        from app.micro_apps.loan_onboarding.routes.packages import router as packages_router
        router.include_router(packages_router)
    except ImportError:
        pass

    try:
        from app.micro_apps.loan_onboarding.routes.documents import router as documents_router
        router.include_router(documents_router)
    except ImportError:
        pass

    try:
        from app.micro_apps.loan_onboarding.routes.validation import router as validation_router
        router.include_router(validation_router)
    except ImportError:
        pass

    try:
        from app.micro_apps.loan_onboarding.routes.review import router as review_router
        router.include_router(review_router)
    except ImportError:
        pass

    try:
        from app.micro_apps.loan_onboarding.routes.rules import router as rules_router
        router.include_router(rules_router)
    except ImportError:
        pass

    try:
        from app.micro_apps.loan_onboarding.routes.overrides import router as overrides_router
        router.include_router(overrides_router)
    except ImportError:
        pass

    try:
        from app.micro_apps.loan_onboarding.routes.extraction import router as extraction_router
        router.include_router(extraction_router)
    except ImportError:
        pass

    try:
        from app.micro_apps.loan_onboarding.routes.extraction_overrides import (
            router as extraction_overrides_router,
        )
        router.include_router(extraction_overrides_router)
    except ImportError:
        pass

    try:
        from app.micro_apps.loan_onboarding.routes.compliance import (
            router as compliance_router,
        )
        router.include_router(compliance_router)
    except ImportError:
        pass

    @router.get("/")
    async def loan_onboarding_root():
        return {"app": "Loan Onboarding", "status": "ready"}

    return router
