"""Service-layer exceptions.

These are raised by service functions and automatically converted to HTTP
responses by the exception handlers registered in create_app(). This keeps
services decoupled from FastAPI/HTTP concerns.

Usage in services:
    from app.core.exceptions import NotFoundError
    raise NotFoundError("Pack", pack_id)

Usage in routes:
    # No try/except needed — the global handler converts to 404/409 automatically.
    pack = await pack_service.get_pack_or_raise(db, org_id, pack_id)
"""


class ServiceError(Exception):
    """Base for all service-layer errors."""

    def __init__(self, message: str, status_code: int = 500):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class AuthenticationError(ServiceError):
    """Authentication failed (maps to HTTP 401)."""

    def __init__(self, message: str = "Invalid credentials"):
        super().__init__(message, status_code=401)


class NotFoundError(ServiceError):
    """Resource not found (maps to HTTP 404)."""

    def __init__(self, resource: str = "Resource", identifier: object = None):
        detail = f"{resource} not found" if not identifier else f"{resource} not found: {identifier}"
        super().__init__(detail, status_code=404)


class ValidationError(ServiceError):
    """Invalid input or failed validation (maps to HTTP 400)."""

    def __init__(self, message: str = "Validation error"):
        super().__init__(message, status_code=400)


class ForbiddenError(ServiceError):
    """Access denied to the requested resource (maps to HTTP 403)."""

    def __init__(self, message: str = "Forbidden"):
        super().__init__(message, status_code=403)


class ConflictError(ServiceError):
    """Operation conflicts with current state (maps to HTTP 409)."""

    def __init__(self, message: str = "Conflict"):
        super().__init__(message, status_code=409)
