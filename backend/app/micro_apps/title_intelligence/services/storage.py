"""Re-export from platform-level storage module.

Storage is a platform concern, not TI-specific. All classes and the factory
function now live in app.services.storage. This shim preserves backward
compatibility for existing TI imports.
"""

from app.services.storage import (  # noqa: F401
    StorageProvider,
    LocalStorage,
    S3Storage,
    get_storage,
)
