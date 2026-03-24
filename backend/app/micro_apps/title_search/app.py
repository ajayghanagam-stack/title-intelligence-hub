from fastapi import APIRouter

from app.micro_apps.base import MicroAppBase
from app.micro_apps.title_search.routes import get_ts_router


class TitleSearchMicroApp(MicroAppBase):
    @property
    def slug(self) -> str:
        return "title-search"

    @property
    def name(self) -> str:
        return "Title Search & Abstracting"

    @property
    def description(self) -> str:
        return "Automated county record searches, chain-of-title construction, and abstract package generation"

    @property
    def icon(self) -> str:
        return "search"

    def get_router(self) -> APIRouter:
        return get_ts_router()

    def get_models(self) -> list[type]:
        from app.micro_apps.title_search.models import (
            TAOrder, TASourceAssignment, TARawDocument, TADocument,
            TAChainLink, TAFlag, TAReview, TAPackage, TACountySource,
            TAPipelineRun,
        )
        return [
            TAOrder, TASourceAssignment, TARawDocument, TADocument,
            TAChainLink, TAFlag, TAReview, TAPackage, TACountySource,
            TAPipelineRun,
        ]


micro_app = TitleSearchMicroApp()
