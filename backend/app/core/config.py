"""
Application configuration.

All configuration is read from environment variables (optionally loaded from
a local .env file via python-dotenv). Nothing sensitive is hardcoded.
"""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # General
    APP_NAME: str = "Document Intelligence Platform"
    ENVIRONMENT: str = "development"
    API_V1_PREFIX: str = "/api/v1"
    LOG_LEVEL: str = "INFO"

    # CORS
    CORS_ORIGINS: str = "*"  # comma-separated list, "*" allows all

    # File handling
    MAX_PAGE_COUNT: int = 3
    MAX_FILE_SIZE_MB: int = 15
    ALLOWED_CONTENT_TYPES: str = "application/pdf,image/jpeg,image/jpg,image/png"
    UPLOAD_TMP_DIR: str = "/tmp/doc_intel_uploads"

    # Database
    # Free Render services do not support persistent disks; use managed Postgres for durable data.
    DATABASE_URL: str = "sqlite:///./document_intelligence.db"

    # OCR
    # 150 DPI is sufficient for most invoices and reduces raster/OCR latency.
    OCR_DPI: int = 150
    OCR_MAX_IMAGE_DIM: int = 1400
    OCR_TIMEOUT_SECONDS: int = 30
    TESSERACT_CMD: str | None = None  # override path to tesseract binary if needed

    # LLM extraction — provider-agnostic. Defaults to Google Gemini because its
    # free tier (Flash models) needs no credit card, which matters for a
    # zero-budget evaluation deployment. Set LLM_PROVIDER=anthropic to use
    # Claude instead (requires a funded Anthropic account).
    LLM_PROVIDER: str = "gemini"

    GEMINI_API_KEY: str | None = None
    GEMINI_MODEL: str = "gemini-3.6-flash"

    ANTHROPIC_API_KEY: str | None = None
    ANTHROPIC_MODEL: str = "claude-sonnet-4-6"

    # Keep synchronous free-tier requests bounded; transient failures get one retry.
    LLM_REQUEST_TIMEOUT_SECONDS: int = 40
    LLM_MAX_RETRIES: int = 1

    @property
    def active_llm_model(self) -> str:
        return self.GEMINI_MODEL if self.LLM_PROVIDER == "gemini" else self.ANTHROPIC_MODEL

    # Financial validation tolerance
    VALIDATION_ABS_TOLERANCE: float = 1.0     # absolute currency-unit tolerance
    VALIDATION_REL_TOLERANCE: float = 0.01    # 1% relative tolerance

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        if self.CORS_ORIGINS.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def allowed_content_type_list(self) -> list[str]:
        return [c.strip() for c in self.ALLOWED_CONTENT_TYPES.split(",") if c.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
