from fastapi import APIRouter

from app.micro_apps.title_intelligence.routes.packs import router as packs_router
from app.micro_apps.title_intelligence.routes.pages import router as pages_router
from app.micro_apps.title_intelligence.routes.extractions import router as extractions_router
from app.micro_apps.title_intelligence.routes.flags import router as flags_router
from app.micro_apps.title_intelligence.routes.chat import router as chat_router
from app.micro_apps.title_intelligence.routes.reports import router as reports_router
from app.micro_apps.title_intelligence.routes.search import router as search_router
from app.micro_apps.title_intelligence.routes.sections import router as sections_router


def get_ti_router() -> APIRouter:
    router = APIRouter(tags=["title-intelligence"])

    router.include_router(packs_router)
    router.include_router(pages_router)
    router.include_router(extractions_router)
    router.include_router(sections_router)
    router.include_router(flags_router)
    router.include_router(chat_router)
    router.include_router(reports_router)
    router.include_router(search_router)

    @router.get("/")
    async def title_intelligence_root():
        return {"app": "Title Intelligence", "status": "ready"}

    return router
