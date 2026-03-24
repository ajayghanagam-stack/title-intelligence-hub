import importlib
import logging
import re
from pathlib import Path

from app.micro_apps.base import MicroAppBase

logger = logging.getLogger(__name__)

_registry: dict[str, MicroAppBase] = {}

# Slug must be lowercase alphanumeric with hyphens, 2-50 chars
_SLUG_RE = re.compile(r"^[a-z][a-z0-9-]{1,48}[a-z0-9]$")


def discover_micro_apps() -> dict[str, MicroAppBase]:
    """Auto-discover micro app modules under app/micro_apps/."""
    if _registry:
        return _registry

    package_dir = Path(__file__).parent
    for item in package_dir.iterdir():
        if item.is_dir() and (item / "__init__.py").exists() and item.name != "__pycache__":
            try:
                module = importlib.import_module(f"app.micro_apps.{item.name}")
                micro_app = getattr(module, "micro_app", None)
                if micro_app is None:
                    continue
                if not isinstance(micro_app, MicroAppBase):
                    logger.warning(
                        "Skipping '%s': micro_app is not a MicroAppBase instance", item.name
                    )
                    continue
                if not _SLUG_RE.match(micro_app.slug):
                    logger.warning(
                        "Skipping '%s': invalid slug '%s' (must match %s)",
                        item.name, micro_app.slug, _SLUG_RE.pattern,
                    )
                    continue
                _registry[micro_app.slug] = micro_app
                logger.info("Registered micro app: %s (%s)", micro_app.slug, micro_app.name)
            except Exception as e:
                logger.error("Failed to load micro app '%s': %s", item.name, e)

    return _registry


def get_registry() -> dict[str, MicroAppBase]:
    return _registry
