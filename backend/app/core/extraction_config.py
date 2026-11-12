"""Contracts and validation types for ai extraction."""

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class ExtractionSettings(BaseSettings):
    """Read like app.inference's settings: process environment only, never .env."""

    model_config = SettingsConfigDict(
        env_prefix="RESOLVE_EXTRACTION_",
        env_file=None,
        extra="ignore",
        hide_input_in_errors=True,
        populate_by_name=True,
    )

    enabled: bool = False
    # The provider key is app.inference's RESOLVE_AI_GROQ_KEY, so one secret
    # serves both features and is configured in one place.
    groq_key: SecretStr | None = Field(
        default=None, validation_alias="RESOLVE_AI_GROQ_KEY"
    )
    # llama-3.3-70b-versatile returned 404 model_not_found for the owner's key.
    model: str = "openai/gpt-oss-120b"
    # Separate from app.inference's RESOLVE_AI_TIMEOUT_SECONDS, which has its own bounds.
    timeout_seconds: float = Field(20, gt=0, le=120)
    # Per merchant per UTC day, counted in this process only (see app.ai_usage).
    daily_token_limit: int = Field(100_000, ge=0)
