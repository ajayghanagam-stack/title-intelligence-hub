from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@db:5432/title_intelligence_hub"

    # JWT Auth
    JWT_SECRET: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRATION_MINUTES: int = 1440  # 24 hours

    # AI Provider
    AI_PLATFORM: Literal["anthropic", "bedrock", "openai", "azure"] = "anthropic"
    ANTHROPIC_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    AZURE_API_KEY: str = ""
    AZURE_API_BASE: str = ""
    AZURE_API_VERSION: str = "2024-02-01"

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
