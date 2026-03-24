import logging
import time

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi.responses import JSONResponse, PlainTextResponse

from app.core.deps import get_db
from app.core.metrics import metrics
from app.micro_apps.registry import get_registry

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check():
    """Lightweight liveness probe — always returns 200."""
    return {"status": "healthy"}


@router.get("/health/ready")
async def readiness_check(db: AsyncSession = Depends(get_db)):
    """Deep readiness probe — checks DB connectivity and reports registered apps.

    Returns 200 if the system is fully operational, 503 if DB is unreachable.
    """
    checks: dict = {}

    # DB connectivity
    try:
        t0 = time.monotonic()
        await db.execute(text("SELECT 1"))
        db_ms = round((time.monotonic() - t0) * 1000, 1)
        checks["database"] = {"status": "ok", "latency_ms": db_ms}
    except Exception as e:
        logger.error("Health check DB failure: %s", e)
        checks["database"] = {"status": "error", "detail": "Database unreachable"}

    # Registered micro apps
    registry = get_registry()
    checks["micro_apps"] = {
        "count": len(registry),
        "slugs": sorted(registry.keys()),
    }

    # Overall status
    all_ok = checks["database"]["status"] == "ok"
    status_code = 200 if all_ok else 503

    return JSONResponse(
        status_code=status_code,
        content={
            "status": "ready" if all_ok else "degraded",
            "checks": checks,
        },
    )


@router.get("/metrics")
async def get_metrics():
    """Prometheus-compatible metrics endpoint."""
    return PlainTextResponse(
        content=metrics.expose(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
