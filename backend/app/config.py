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

    # AI Provider selection — "claude" (default), "gemini", or "hybrid" (Gemini vision + Claude extraction)
    AI_PROVIDER: Literal["gemini", "claude", "hybrid"] = "claude"

    # Per-agent provider overrides (empty string = use AI_PROVIDER)
    TI_CHAT_PROVIDER: Literal["gemini", "claude", ""] = ""
    TA_AI_PROVIDER: Literal["gemini", "claude", ""] = "claude"

    # Gemini / Vertex AI
    GOOGLE_API_KEY: str = ""  # AI Studio API key (used when VERTEX_AI=false)
    VERTEX_AI: bool = False  # Set True to use Vertex AI instead of AI Studio
    GOOGLE_CLOUD_PROJECT: str = ""  # GCP project ID (required when VERTEX_AI=true)
    GOOGLE_CLOUD_REGION: str = "us-central1"  # Vertex AI region

    # Claude (Anthropic)
    ANTHROPIC_API_KEY: str = ""

    # Claude-specific examiner settings
    CLAUDE_EXAMINER_BATCH_SIZE: int = 8          # image pages per batch (Claude slower output)
    CLAUDE_EXAMINER_BATCH_SIZE_TEXT: int = 25     # text pages per batch (larger = fewer API calls)
    CLAUDE_EXAMINER_RENDER_DPI: int = 100         # 100 DPI balances quality vs size (avoids 5MB limit)
    CLAUDE_EXAMINER_CONCURRENCY: int = 8          # parallel batch calls (higher throughput)
    CLAUDE_EXAMINER_STAGGER_MS: int = 100         # ms between batch launches (reduced from 300)
    CLAUDE_EXAMINER_RPM: int = 50                 # proactive requests/minute limit (0 = disabled)

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
    TSA_TEMPORAL_TASK_QUEUE: str = "title-search"
    LO_TEMPORAL_TASK_QUEUE: str = "loan-onboarding"

    # --- Loan Onboarding micro-app settings ---
    # Model IDs are configurable so they can be bumped (e.g. to gemini-3-flash,
    # claude-opus-4-7) when those models become available without code changes.
    # Leave blank ("") to use each agent's default model (CLAUDE_MODEL from
    # claude_provider.py for validator/reasoner; the gemini default for the
    # classifier). Set a litellm-compatible id like "anthropic/claude-sonnet-4-6"
    # or "gemini/gemini-2.5-flash" to override.
    LO_CLASSIFIER_MODEL: str = ""
    LO_VALIDATOR_MODEL: str = ""
    LO_REASONER_MODEL: str = ""
    # Stacks with overall_confidence below this threshold go to HITL review.
    # Can be overridden per-package at creation time.
    LO_HITL_THRESHOLD: float = 0.96
    # Max upload size for loan bundles (default 500 MB). Mortgage packets
    # routinely exceed the platform-wide 100 MB cap, so this overrides
    # FILE_UPLOAD_MAX_SIZE for the loan-onboarding upload route only.
    LO_FILE_UPLOAD_MAX_SIZE: int = 524288000  # 500 MB

    # Pipeline mode: native_pdf sends PDF chunks directly to Gemini; legacy renders to JPEG first
    PIPELINE_MODE: Literal["native_pdf", "legacy"] = "native_pdf"

    # Native PDF examiner settings
    NATIVE_PDF_BATCH_SIZE: int = 20       # pages per PDF chunk sent to Gemini
    NATIVE_PDF_CONCURRENCY: int = 12      # max parallel Gemini calls (semaphore)
    NATIVE_PDF_STAGGER_MS: int = 0        # ms delay between chunk launches (rate limit protection)

    # Page triage — lightweight LLM classification before deep extraction
    TRIAGE_ENABLED: bool = True           # set False to skip triage (all pages → examine)
    TRIAGE_SKIP_BELOW: int = 200          # skip LLM triage for docs under this page count
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

    # TSA Research mode: "grounded" uses Claude web search, "scraper" uses legacy portal scraping
    TSA_RESEARCH_MODE: Literal["grounded", "scraper"] = "grounded"

    # Title Examiner (single-pass Gemini Vision pipeline)
    EXAMINER_BATCH_SIZE: int = 10        # Max pages per batch (image pages)
    EXAMINER_BATCH_SIZE_TEXT: int = 25   # Max pages per batch (text-only pages, cheaper)
    EXAMINER_BATCH_OVERLAP: int = 1
    EXAMINER_BATCH_COOLDOWN: float = 0.0
    EXAMINER_CALL_TIMEOUT: int = 300
    EXAMINER_MAX_OUTPUT_TOKENS: int = 16384
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

    @property
    def _has_gemini_credentials(self) -> bool:
        """Check if either AI Studio API key or Vertex AI credentials are configured."""
        if self.VERTEX_AI:
            return bool(self.GOOGLE_CLOUD_PROJECT)
        return bool(self.GOOGLE_API_KEY)

    @model_validator(mode="after")
    def _validate_chat_provider_keys(self) -> "Settings":
        """Ensure the required API key is present when TI_CHAT_PROVIDER is set."""
        if self.TI_CHAT_PROVIDER == "claude" and not self.ANTHROPIC_API_KEY:
            raise ValueError(
                "TI_CHAT_PROVIDER='claude' requires ANTHROPIC_API_KEY"
            )
        if self.TI_CHAT_PROVIDER == "gemini" and not self._has_gemini_credentials:
            raise ValueError(
                "TI_CHAT_PROVIDER='gemini' requires GOOGLE_API_KEY or VERTEX_AI credentials"
            )
        return self

    @model_validator(mode="after")
    def _validate_ta_provider_keys(self) -> "Settings":
        """Ensure the required API key is present when TA_AI_PROVIDER is set."""
        if self.TA_AI_PROVIDER == "claude" and not self.ANTHROPIC_API_KEY:
            raise ValueError(
                "TA_AI_PROVIDER='claude' requires ANTHROPIC_API_KEY"
            )
        if self.TA_AI_PROVIDER == "gemini" and not self._has_gemini_credentials:
            raise ValueError(
                "TA_AI_PROVIDER='gemini' requires GOOGLE_API_KEY or VERTEX_AI credentials"
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

    @model_validator(mode="after")
    def _coerce_hybrid_settings(self) -> "Settings":
        """Force native_pdf pipeline mode for hybrid (Gemini handles vision pass)."""
        if self.AI_PROVIDER == "hybrid":
            if self.PIPELINE_MODE != "native_pdf":
                object.__setattr__(self, "PIPELINE_MODE", "native_pdf")
        return self

    @model_validator(mode="after")
    def _validate_hybrid_keys(self) -> "Settings":
        """Hybrid mode requires both Google and Anthropic API keys."""
        if self.AI_PROVIDER == "hybrid":
            if not self._has_gemini_credentials:
                raise ValueError(
                    "AI_PROVIDER='hybrid' requires GOOGLE_API_KEY or VERTEX_AI credentials "
                    "(Gemini handles the vision/OCR pass)"
                )
            if not self.ANTHROPIC_API_KEY:
                raise ValueError(
                    "AI_PROVIDER='hybrid' requires ANTHROPIC_API_KEY "
                    "(Claude handles the extraction pass)"
                )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
