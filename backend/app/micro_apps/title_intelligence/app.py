from fastapi import APIRouter

from app.micro_apps.base import MicroAppBase
from app.micro_apps.title_intelligence.routes import get_ti_router


class TitleIntelligenceMicroApp(MicroAppBase):
    @property
    def slug(self) -> str:
        return "title-intelligence"

    @property
    def name(self) -> str:
        return "Title Intelligence"

    @property
    def description(self) -> str:
        return "AI-powered title commitment analysis with risk flagging and readiness scoring"

    @property
    def icon(self) -> str:
        return "file-search"

    def get_router(self) -> APIRouter:
        return get_ti_router()

    def get_models(self) -> list[type]:
        from app.micro_apps.title_intelligence.models import (
            Pack, PackFile, Page, Section, Extraction,
            Flag, Review, TextChunk, ChatMessage, PipelineRun,
        )
        return [Pack, PackFile, Page, Section, Extraction, Flag, Review, TextChunk, ChatMessage, PipelineRun]


micro_app = TitleIntelligenceMicroApp()
