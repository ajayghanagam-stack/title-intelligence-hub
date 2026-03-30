from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Database — supports both asyncpg (ASYNC_DATABASE_URL) and standard postgres (DATABASE_URL)
    # On Replit, DATABASE_URL is set automatically as postgresql://...; ASYNC_DATABASE_URL
    # wraps it with asyncpg driver for SQLAlchemy async engine use.
    ASYNC_DATABASE_URL: str = ""
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@db:5432/title_intelligence_hub"

    @property
    def effective_database_url(self) -> str:
        """Return the asyncpg-compatible URL for SQLAlchemy async engine."""
        if self.ASYNC_DATABASE_URL:
            return self.ASYNC_DATABASE_URL
        url = self.DATABASE_URL
        if url.startswith("postgresql://") or url.startswith("postgres://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
            url = url.replace("postgres://", "postgresql+asyncpg://", 1)
            if "sslmode=disable" in url:
                url = url.replace("sslmode=disable", "ssl=false")
        return url

    # JWT Auth
    JWT_SECRET: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRATION_MINUTES: int = 1440  # 24 hours

    # AI Provider selection — "gemini" (default) or "claude"
    AI_PROVIDER: Literal["gemini", "claude"] = "gemini"

    # Gemini (default)
    GOOGLE_API_KEY: str = ""

    # Claude (Anthropic)
    ANTHROPIC_API_KEY: str = ""

    # Claude-specific examiner settings
    CLAUDE_EXAMINER_BATCH_SIZE: int = 8          # image pages per batch (Claude slower output)
    CLAUDE_EXAMINER_BATCH_SIZE_TEXT: int = 15     # text pages per batch
    CLAUDE_EXAMINER_RENDER_DPI: int = 150         # higher DPI for Claude vision accuracy
    CLAUDE_EXAMINER_CONCURRENCY: int = 5          # parallel batch calls (Anthropic rate limits)
    CLAUDE_EXAMINER_STAGGER_MS: int = 300         # ms between batch launches

    # OCR
    TESSERACT_PATH: str = ""  # Custom tesseract binary path (leave empty for system default)

    # Storage
    STORAGE_PROVIDER: Literal["local", "s3"] = "local"
    STORAGE_PATH: str = "./storage"  # Local storage base path
    S3_ENDPOINT: str = ""  # S3/MinIO endpoint URL (leave empty for AWS S3)
    S3_BUCKET: str = ""
    S3_ACCESS_KEY: str = ""
    S3_SECRET_KEY: str = ""
    S3_REGION: str = "us-east-1"
    FILE_UPLOAD_MAX_SIZE: int = 100 * 1024 * 1024  # 100 MB

    # Pipeline
    PIPELINE_BACKEND: Literal["background_tasks", "temporal"] = "temporal"
    TEMPORAL_ADDRESS: str = "localhost:7233"
    TEMPORAL_NAMESPACE: str = "default"
    TEMPORAL_TASK_QUEUE: str = "title-intelligence"

    # Pipeline mode: native_pdf sends PDF chunks directly to Gemini; legacy renders to JPEG first
    PIPELINE_MODE: Literal["native_pdf", "legacy"] = "native_pdf"

    # Native PDF examiner settings
    NATIVE_PDF_BATCH_SIZE: int = 20       # pages per PDF chunk sent to Gemini
    NATIVE_PDF_CONCURRENCY: int = 12      # max parallel Gemini calls (semaphore)
    NATIVE_PDF_STAGGER_MS: int = 0        # ms delay between chunk launches (rate limit protection)

    # Page triage — lightweight LLM classification before deep extraction
    TRIAGE_ENABLED: bool = True           # set False to skip triage (all pages → examine)
    TRIAGE_SKIP_BELOW: int = 80           # skip LLM triage for docs under this page count
    TRIAGE_CHUNK_SIZE: int = 50           # pages per triage chunk (split larger PDFs)
    TRIAGE_CONCURRENCY: int = 4           # max parallel triage LLM calls

    # Document grouping — group content pages into logical documents before extraction
    GROUPING_ENABLED: bool = True         # set False to use fixed-size chunking

    # Adaptive chunk sizing — adjusts batch size based on page text complexity
    ADAPTIVE_CHUNK_SIZING: bool = True    # set False for fixed-size batching

    # Specialized extraction — route document groups to type-specific extractors
    SPECIALIZED_EXTRACTION_ENABLED: bool = True  # set False to use generic extractor for all

    # Summary generation mode: data_driven uses template from structured data (fast, deterministic);
    # llm calls Gemini for narrative summary (10-15s, non-deterministic)
    SUMMARY_MODE: Literal["data_driven", "llm"] = "data_driven"

    # Title Examiner (single-pass Gemini Vision pipeline)
    EXAMINER_BATCH_SIZE: int = 10        # Max pages per batch (image pages)
    EXAMINER_BATCH_SIZE_TEXT: int = 25   # Max pages per batch (text-only pages, cheaper)
    EXAMINER_BATCH_OVERLAP: int = 1
    EXAMINER_BATCH_COOLDOWN: float = 0.0
    EXAMINER_CALL_TIMEOUT: int = 300
    EXAMINER_MAX_OUTPUT_TOKENS: int = 65536
    EXAMINER_RENDER_DPI: int = 72

    # CORS
    CORS_ORIGINS: list[str] = ["http://localhost:3000"]

    # Debug mode — allows insecure defaults (JWT secret, etc.)
    DEBUG: bool = False

    model_config = {"env_file": ".env", "extra": "ignore"}

    @model_validator(mode="after")
    def validate_jwt_secret(self) -> "Settings":
        if not self.DEBUG and self.JWT_SECRET == "change-me-in-production":
            raise ValueError(
                "CRITICAL: JWT_SECRET is set to the insecure default. "
                "Set a strong secret via JWT_SECRET env var, or set DEBUG=true for development."
            )
        return self

    @model_validator(mode="after")
    def _coerce_claude_settings(self) -> "Settings":
        """Force legacy pipeline mode and higher DPI when using Claude."""
        if self.AI_PROVIDER == "claude":
            if self.PIPELINE_MODE == "native_pdf":
                object.__setattr__(self, "PIPELINE_MODE", "legacy")
            object.__setattr__(self, "EXAMINER_RENDER_DPI", self.CLAUDE_EXAMINER_RENDER_DPI)
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
