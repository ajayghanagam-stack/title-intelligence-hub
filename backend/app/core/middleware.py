"""Pure-ASGI middleware for request id, metrics, tenant context, and
micro-app subscription gating.

These were originally implemented on top of `BaseHTTPMiddleware`, which
wraps the ASGI `receive` callable in an asyncio queue. With four layers
stacked, every request body chunk gets shovelled through four queues
before reaching the handler — adding several seconds of latency to a
75 MB multipart upload (observed: ~140 ms server-side handler time vs
multi-second perceived "uploading…" phase). None of these middlewares
read the body, so converting them to pure ASGI lets the body stream
straight through unchanged.
"""
import json
import logging
import re
import time
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker
from starlette.datastructures import MutableHeaders

from app.models.subscription import Subscription
from app.models.micro_app import MicroApp

_upload_log = logging.getLogger("app.upload_timing")

# Diagnostic: matches LO file-upload POSTs so we can split the wall clock into
# (browser→first-byte) + (first-byte→last-byte) + (last-byte→handler-entry).
# Without this split, the existing handler-entry timing tells us nothing about
# where the perceived 2-minute upload time is actually being spent.
_UPLOAD_TIMING_PATH = re.compile(
    r"^/api/v1/apps/loan-onboarding/packages/[^/]+/files/?$"
)


# Phase 4 Batch 4.9 — when LO_LEGACY_REDIRECT_ENABLED, the legacy
# ``/api/v1/apps/loan-onboarding/packages/...`` paths return ``301`` to the
# corresponding ``/loans/...`` route. The collection roots
# ``/packages`` and ``/packages/`` are handled too.
_LO_LEGACY_PATH_PREFIX = "/api/v1/apps/loan-onboarding/packages"


# Paths that don't require tenant context
PUBLIC_PATHS = {"/api/v1/health", "/api/v1/health/ready", "/api/v1/metrics", "/docs", "/openapi.json", "/redoc"}
# Prefixes that don't require tenant context
PUBLIC_PREFIXES = ("/api/v1/auth/", "/api/v1/admin/")

# Pattern to match micro app routes
MICRO_APP_ROUTE_PATTERN = re.compile(r"^/api/v1/apps/([^/]+)/")


def _ensure_state(scope: dict) -> dict:
    """Get or create the per-request state dict that backs `request.state`."""
    state = scope.get("state")
    if state is None:
        state = {}
        scope["state"] = state
    return state


async def _send_json_error(send, status_code: int, detail: str) -> None:
    """Emit a JSON error response without going through Starlette's Response."""
    body = json.dumps({"detail": detail}).encode("utf-8")
    await send({
        "type": "http.response.start",
        "status": status_code,
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode("ascii")),
        ],
    })
    await send({
        "type": "http.response.body",
        "body": body,
    })


class UploadTimingMiddleware:
    """Diagnostic-only: times the body-receive phase of LO file uploads.

    Splits the wall-clock for `POST /api/v1/apps/loan-onboarding/packages/{id}/files`
    into:
      - first_byte_after_headers: time from middleware entry to first ASGI body chunk
        (ASGI server receives Request-Line + headers before our handler is invoked,
        so this is approximately "client started sending body" → "first byte arrived")
      - body_transfer: time between first and last body chunk (network + spool)
      - parse_to_handler: gap between last body chunk and handler entry, computed
        from the existing `lo_upload: handler entered` log line

    Logs at INFO under `app.upload_timing`. Activated only on the upload route so
    it adds zero overhead to other traffic.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        if scope.get("method") != "POST":
            return await self.app(scope, receive, send)
        if not _UPLOAD_TIMING_PATH.match(scope.get("path", "")):
            return await self.app(scope, receive, send)

        t_entry = time.monotonic()
        first_byte_t: list[float] = []
        last_byte_t: list[float] = []
        total_bytes = 0

        async def receive_wrapper():
            nonlocal total_bytes
            message = await receive()
            if message["type"] == "http.request":
                now = time.monotonic()
                if not first_byte_t:
                    first_byte_t.append(now)
                    _upload_log.info(
                        "upload_timing: first body chunk arrived after %.2fs (path=%s)",
                        now - t_entry, scope.get("path"),
                    )
                body = message.get("body", b"")
                total_bytes += len(body)
                if not message.get("more_body", False):
                    last_byte_t.append(now)
                    _upload_log.info(
                        "upload_timing: last body chunk after %.2fs total (transfer=%.2fs, %.1f MB received)",
                        now - t_entry,
                        (now - first_byte_t[0]) if first_byte_t else 0.0,
                        total_bytes / 1024 / 1024,
                    )
            elif message["type"] == "http.disconnect":
                _upload_log.warning(
                    "upload_timing: client disconnected after %.2fs, %.1f MB received",
                    time.monotonic() - t_entry, total_bytes / 1024 / 1024,
                )
            return message

        await self.app(scope, receive_wrapper, send)


class RequestIdMiddleware:
    """Generates or propagates a unique request ID for correlation.

    Reads X-Request-Id from the incoming request headers. If absent,
    generates a 12-char UUID hex. Writes the value onto request.state and
    echoes it back on the response.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        # Pull X-Request-Id from headers (header keys are bytes, lowercased)
        incoming = None
        for name, value in scope.get("headers", ()):
            if name == b"x-request-id":
                incoming = value.decode("latin-1")
                break
        request_id = incoming or uuid.uuid4().hex[:12]

        _ensure_state(scope)["request_id"] = request_id

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-Request-Id"] = request_id
            await send(message)

        await self.app(scope, receive, send_wrapper)


class MetricsMiddleware:
    """Tracks request count and latency per method+status."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        from app.core.metrics import metrics

        method = scope.get("method", "")
        start = time.monotonic()
        status_holder: dict[str, int] = {"code": 500}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status_holder["code"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration = time.monotonic() - start
            metrics.inc("http_requests_total", labels={
                "method": method, "status": str(status_holder["code"]),
            })
            metrics.observe("http_request_duration_seconds", duration, labels={
                "method": method,
            })


class TenantContextMiddleware:
    """Resolves org_id from the X-Org-Id header for non-public API routes."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        path: str = scope.get("path", "")

        # Skip public paths and non-API routes
        if path in PUBLIC_PATHS or not path.startswith("/api/"):
            return await self.app(scope, receive, send)

        # Skip public prefixes (auth, admin)
        for prefix in PUBLIC_PREFIXES:
            if path.startswith(prefix):
                return await self.app(scope, receive, send)

        # Read X-Org-Id from headers
        org_id_raw: str | None = None
        for name, value in scope.get("headers", ()):
            if name == b"x-org-id":
                org_id_raw = value.decode("latin-1")
                break

        if org_id_raw:
            try:
                _ensure_state(scope)["org_id"] = uuid.UUID(org_id_raw)
            except ValueError:
                return await _send_json_error(send, 400, "Invalid X-Org-Id header")

        await self.app(scope, receive, send)


class LOLegacyRedirectMiddleware:
    """Phase 4 Batch 4.9 — 301-redirects ``/packages/*`` LO paths to ``/loans/*``.

    Activated only when ``settings.LO_LEGACY_REDIRECT_ENABLED`` is True.
    The flag defaults to False so the existing frontend keeps working
    unchanged. Flip it to True only after Phase 5 ports the UI fully to
    ``/loans/*``.

    Strict 1:1 path swap (``packages`` → ``loans``). Endpoints that do not
    have a ``/loans/*`` analogue (e.g. ``/packages/{id}/stacks`` whose
    LogikIntake equivalent is ``/loans/{id}/documents``) will redirect to
    a 404 — that's intentional, those paths are no longer reachable from
    the new frontend so emitting a 301 is correct from a cache-invalidation
    standpoint.
    """

    def __init__(self, app, enabled: bool):
        self.app = app
        self.enabled = enabled

    async def __call__(self, scope, receive, send):
        if not self.enabled or scope["type"] != "http":
            return await self.app(scope, receive, send)

        path: str = scope.get("path", "")
        if not path.startswith(_LO_LEGACY_PATH_PREFIX):
            return await self.app(scope, receive, send)

        # Compute the /loans/... path. Handles both the bare collection
        # (``/packages`` or ``/packages/``) and any nested resource.
        suffix = path[len(_LO_LEGACY_PATH_PREFIX):]
        new_path = "/api/v1/apps/loan-onboarding/loans" + suffix

        query = scope.get("query_string") or b""
        location = new_path.encode("ascii")
        if query:
            location += b"?" + query

        await send({
            "type": "http.response.start",
            "status": 301,
            "headers": [
                (b"location", location),
                (b"content-length", b"0"),
            ],
        })
        await send({"type": "http.response.body", "body": b""})


class MicroAppAccessMiddleware:
    """Checks that the org has an active subscription for the requested micro app."""

    def __init__(self, app, session_factory: async_sessionmaker):
        self.app = app
        self.session_factory = session_factory

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        path: str = scope.get("path", "")
        match = MICRO_APP_ROUTE_PATTERN.match(path)
        if not match:
            return await self.app(scope, receive, send)

        app_slug = match.group(1)
        state = scope.get("state") or {}
        org_id: Any = state.get("org_id")

        if org_id is None:
            return await _send_json_error(send, 403, "Organization context required")

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
            return await _send_json_error(send, 403, "No active subscription for this app")

        await self.app(scope, receive, send)
