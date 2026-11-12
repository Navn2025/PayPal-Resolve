"""Contracts and validation types for inference."""

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class InvestigationSettings(BaseSettings):
    # Deliberately never reads .env. Operators must explicitly inject configuration.
    model_config = SettingsConfigDict(
        env_prefix="RESOLVE_AI_",
        env_file=None,
        extra="ignore",
        hide_input_in_errors=True,
    )
    enabled: bool = False
    groq_key: SecretStr | None = None
    openrouter_key: SecretStr | None = None
    groq_model: str = "openai/gpt-oss-20b"
    openrouter_model: str = "openai/gpt-oss-120b"
    approved_groq_models: tuple[str, ...] = (
        "openai/gpt-oss-20b",
        "openai/gpt-oss-120b",
    )
    approved_openrouter_models: tuple[str, ...] = (
        "xingchen-agi/xing4.0-29b-a4b:free",
        "openai/gpt-oss-120b",
    )
    openrouter_routes: tuple[str, ...] = ("phala",)
    # Direct Groq has no request-level ZDR enforcement. Default policy blocks it.
    data_policy: str = "zdr_required"
    allow_sandbox_refresh: bool = False
    timeout_seconds: float = Field(default=12, ge=0.1, le=20)
    retries: int = Field(default=1, ge=0, le=1)
    max_tokens: int = Field(default=1800, ge=128, le=2400)
    freshness_seconds: int = Field(default=3600, ge=60, le=86400)
