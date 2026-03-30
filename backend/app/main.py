import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

# Configure logging so pipeline/AI logs are visible
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# Silence noisy third-party loggers that dump full request/response payloads
# (including raw PDF binary bytes from Gemini API calls)
for _noisy in ("httpx", "httpcore", "litellm", "LiteLLM", "google.genai",
               "google.auth", "google.api_core", "googleapis", "urllib3",
               "asyncpg", "grpc", "hpack"):
    _logger = logging.getLogger(_noisy)
    _logger.setLevel(logging.WARNING)
    # LiteLLM adds its own StreamHandler at DEBUG level — remove it
    _logger.handlers = [h for h in _logger.handlers if h.level > logging.INFO]
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.config import get_settings
from app.api.v1.router import api_v1_router
from app.core.middleware import MetricsMiddleware, RequestIdMiddleware, TenantContextMiddleware, MicroAppAccessMiddleware
from app.micro_apps.registry import discover_micro_apps


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Micro app routers are mounted in create_app() — lifespan is for
    # async startup/shutdown tasks (DB pools, background workers, etc.)
    yield


def create_app(session_factory_override=None) -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Title Intelligence Hub",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Middleware execution order is LIFO (last added = outermost = runs first)
    # We need: CORS → TenantContext → MicroAppAccess → route handler
    # So add in reverse order:

    # Micro app access middleware (innermost, runs last before handler)
    if session_factory_override:
        sf = session_factory_override
    else:
        engine = create_async_engine(settings.effective_database_url, echo=False, pool_size=5)
        sf = async_sessionmaker(engine, expire_on_commit=False)
    app.add_middleware(MicroAppAccessMiddleware, session_factory=sf)

    # Tenant context middleware (runs before MicroAppAccess)
    app.add_middleware(TenantContextMiddleware)

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Metrics (tracks request count + latency)
    app.add_middleware(MetricsMiddleware)

    # Request ID (outermost, runs first — before CORS)
    app.add_middleware(RequestIdMiddleware)

    # Service-layer exception → HTTP response conversion
    from app.core.exceptions import ServiceError

    @app.exception_handler(ServiceError)
    async def service_error_handler(request, exc: ServiceError):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.message},
        )

    # Rate limiting — single shared instance from app.core.rate_limit
    from slowapi import _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded
    from app.core.rate_limit import limiter

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # API routes
    app.include_router(api_v1_router)

    # Discover and mount micro app routers
    micro_apps = discover_micro_apps()
    for slug, micro_app in micro_apps.items():
        app.include_router(
            micro_app.get_router(),
            prefix=f"/api/v1/apps/{slug}",
        )

    return app


app = create_app()
