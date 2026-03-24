from abc import ABC, abstractmethod

from fastapi import APIRouter


class MicroAppBase(ABC):
    """Base class for all micro apps.

    Every micro app must subclass this and implement the required abstract
    members. The registry discovers subclasses at startup and mounts their
    routers under /api/v1/apps/{slug}/.

    Required:
        slug: URL-safe identifier (must match directory name)
        name: Human-readable display name
        get_router(): FastAPI APIRouter with all routes

    Optional (override for richer app registry):
        description: Short description for the app marketplace
        icon: Icon identifier (e.g. Lucide icon name)
        get_models(): List of SQLAlchemy model classes for Alembic discovery
    """

    @property
    @abstractmethod
    def slug(self) -> str:
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @property
    def description(self) -> str:
        return ""

    @property
    def icon(self) -> str:
        return "box"

    @abstractmethod
    def get_router(self) -> APIRouter:
        """Return the FastAPI router for this micro app."""
        ...

    def get_models(self) -> list[type]:
        """Return SQLAlchemy model classes owned by this micro app.

        Alembic calls this via the registry to discover all models for
        migration generation. Override in subclasses that define models.
        """
        return []
