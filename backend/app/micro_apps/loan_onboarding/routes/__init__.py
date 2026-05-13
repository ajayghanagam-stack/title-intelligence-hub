from fastapi import APIRouter


def get_lo_router() -> APIRouter:
    """Compose all Loan Onboarding sub-routers.

    Sub-routers are imported lazily so that missing route files don't prevent
    app registration during scaffolding.
    """
    router = APIRouter(tags=["loan-onboarding"])

    # Phase 6 cutover (2026-05-10) — the legacy `/packages/*` public surface is
    # no longer mounted. The `routes.packages` module itself is still imported
    # by `routes.loans` as a service module (`_packages.list_packages`,
    # `download_final_packet`, etc.) so we keep the file on disk but stop
    # registering its router. Same story for `routes.compliance` — the route
    # file is gone, and its model + schema stay until a follow-up drops the
    # `lo_compliance_*` tables.

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
        from app.micro_apps.loan_onboarding.routes.admin_config import (
            router as admin_config_router,
        )
        router.include_router(admin_config_router)
    except ImportError:
        pass

    try:
        from app.micro_apps.loan_onboarding.routes.hard_stop_overrides import (
            router as hard_stop_overrides_router,
        )
        router.include_router(hard_stop_overrides_router)
    except ImportError:
        pass

    try:
        from app.micro_apps.loan_onboarding.routes.remediation import (
            router as remediation_router,
        )
        router.include_router(remediation_router)
    except ImportError:
        pass

    # Phase 4 Batch 4.1 — parallel /loans/* prefix (read-only aliases).
    # Both /packages/* and /loans/* stay live during Phase 4-5 transition.
    try:
        from app.micro_apps.loan_onboarding.routes.loans import (
            router as loans_router,
        )
        router.include_router(loans_router)
    except ImportError:
        pass

    # Phase 4 Batch 4.3-4.8 — operator-flow endpoints (new business logic).
    try:
        from app.micro_apps.loan_onboarding.routes.loans_operator import (
            router as loans_operator_router,
        )
        router.include_router(loans_operator_router)
    except ImportError:
        pass

    @router.get("/")
    async def loan_onboarding_root():
        return {"app": "Loan Onboarding", "status": "ready"}

    return router
