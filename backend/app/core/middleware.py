import uuid
import re

from fastapi import Request, Response, status
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.user import User
from app.models.subscription import Subscription
from app.models.micro_app import MicroApp

# Paths that don't require tenant context
PUBLIC_PATHS = {"/api/v1/health", "/api/v1/health/ready", "/api/v1/metrics", "/docs", "/openapi.json", "/redoc"}
# Prefixes that don't require tenant context
PUBLIC_PREFIXES = ("/api/v1/auth/", "/api/v1/admin/")


class MetricsMiddleware(BaseHTTPMiddleware):
    """Tracks request count and latency per method+path."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        from app.core.metrics import metrics
        import time

        start = time.monotonic()
        response = await call_next(request)
        duration = time.monotonic() - start

        # Normalize path to avoid cardinality explosion from UUIDs
        path = request.url.path
        method = request.method
        status_code = response.status_code

        metrics.inc("http_requests_total", labels={
            "method": method, "status": str(status_code),
        })
        metrics.observe("http_request_duration_seconds", duration, labels={
            "method": method,
        })
        return response


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Generates or propagates a unique request ID for correlation.

    Reads X-Request-Id from the incoming request header. If not present,
    generates a new UUID. Sets on request.state.request_id and adds to
    the response headers.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = request.headers.get("X-Request-Id") or uuid.uuid4().hex[:12]
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-Id"] = request_id
        return response


class TenantContextMiddleware(BaseHTTPMiddleware):
    """Resolves org_id from JWT claims or X-Org-Id header."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Skip for public paths
        if request.url.path in PUBLIC_PATHS or not request.url.path.startswith("/api/"):
            return await call_next(request)

        # Skip for public prefixes (auth routes)
        for prefix in PUBLIC_PREFIXES:
            if request.url.path.startswith(prefix):
                return await call_next(request)

        # Get org_id from X-Org-Id header (sole source of org context)
        org_id_header = request.headers.get("X-Org-Id")
        if org_id_header:
            try:
                request.state.org_id = uuid.UUID(org_id_header)
            except ValueError:
                return Response(
                    content='{"detail":"Invalid X-Org-Id header"}',
                    status_code=status.HTTP_400_BAD_REQUEST,
                    media_type="application/json",
                )

        return await call_next(request)


# Pattern to match micro app routes
MICRO_APP_ROUTE_PATTERN = re.compile(r"^/api/v1/apps/([^/]+)/")


class MicroAppAccessMiddleware(BaseHTTPMiddleware):
    """Checks that the org has an active subscription for the requested micro app."""

    def __init__(self, app, session_factory: async_sessionmaker):
        super().__init__(app)
        self.session_factory = session_factory

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        match = MICRO_APP_ROUTE_PATTERN.match(request.url.path)
        if not match:
            return await call_next(request)

        app_slug = match.group(1)
        org_id = getattr(request.state, "org_id", None)

        if org_id is None:
            return Response(
                content='{"detail":"Organization context required"}',
                status_code=status.HTTP_403_FORBIDDEN,
                media_type="application/json",
            )

        async with self.session_factory() as session:
            result = await session.execute(
                select(Subscription)
                .join(MicroApp, Subscription.app_id == MicroApp.id)
                .where(
                    Subscription.org_id == org_id,
                    MicroApp.slug == app_slug,
                    MicroApp.is_active == True,
                    Subscription.status == "active",
                )
            )
            subscription = result.scalar_one_or_none()

        if subscription is None:
            return Response(
                content='{"detail":"No active subscription for this app"}',
                status_code=status.HTTP_403_FORBIDDEN,
                media_type="application/json",
            )

        return await call_next(request)
