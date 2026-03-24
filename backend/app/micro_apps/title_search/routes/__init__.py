from fastapi import APIRouter

from app.micro_apps.title_search.routes.orders import router as orders_router
from app.micro_apps.title_search.routes.sources import router as sources_router
from app.micro_apps.title_search.routes.county_sources import router as county_sources_router
from app.micro_apps.title_search.routes.documents import router as documents_router
from app.micro_apps.title_search.routes.flags import router as flags_router
from app.micro_apps.title_search.routes.chain import router as chain_router
from app.micro_apps.title_search.routes.packages import router as packages_router


def get_ts_router() -> APIRouter:
    router = APIRouter(tags=["title-search"])

    router.include_router(orders_router)
    router.include_router(sources_router)
    router.include_router(county_sources_router)
    router.include_router(documents_router)
    router.include_router(flags_router)
    router.include_router(chain_router)
    router.include_router(packages_router)

    @router.get("/")
    async def title_search_root():
        return {"app": "Title Search & Abstracting", "status": "ready"}

    return router
