from fastapi import APIRouter

from app.micro_apps.base import MicroAppBase


class TaxSearchMicroApp(MicroAppBase):
    @property
    def slug(self) -> str:
        return "tax-search"

    @property
    def name(self) -> str:
        return "Tax Search & Certification"

    def get_router(self) -> APIRouter:
        router = APIRouter(tags=["tax-search"])

        @router.get("/")
        async def tax_search_root():
            return {"app": self.name, "status": "ready"}

        return router


micro_app = TaxSearchMicroApp()
