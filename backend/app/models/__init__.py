from app.models.base import Base
from app.models.organization import Organization
from app.models.user import User
from app.models.micro_app import MicroApp
from app.models.subscription import Subscription
from app.models.audit_event import AuditEvent

# Micro app models are discovered via the plugin registry's get_models().
# This replaces hard-coded TI imports with a generic mechanism.

_micro_app_models_loaded = False


def ensure_micro_app_models():
    """Import all micro app models so Alembic can discover them on Base.metadata."""
    global _micro_app_models_loaded
    if _micro_app_models_loaded:
        return
    _micro_app_models_loaded = True
    from app.micro_apps.registry import discover_micro_apps
    for _slug, app in discover_micro_apps().items():
        app.get_models()  # Importing the classes registers them on Base.metadata


# Backward compat alias
ensure_ti_models = ensure_micro_app_models


def __getattr__(name):
    """Lazy-load TI model names so existing code like `from app.models import Pack` still works."""
    _ti_names = {
        "Pack", "PackFile", "Page", "Section", "Extraction",
        "Flag", "Review", "TextChunk", "ChatMessage", "PipelineRun",
    }
    if name in _ti_names:
        ensure_micro_app_models()
        import app.micro_apps.title_intelligence.models as ti_models
        return getattr(ti_models, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "Base", "Organization", "User", "MicroApp", "Subscription", "AuditEvent",
    "Pack", "PackFile", "Page", "Section", "Extraction",
    "Flag", "Review", "TextChunk", "ChatMessage", "PipelineRun",
    "ensure_micro_app_models", "ensure_ti_models",
]
