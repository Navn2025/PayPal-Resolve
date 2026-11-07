from pathlib import Path

from pydantic import SecretStr, field_validator
from uuid import UUID
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RESOLVE_", env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8", extra="ignore",
    )

    database_path: Path = BACKEND_DIR / "data" / "resolve.sqlite3"
    paypal_sandbox_enabled: bool = False
    paypal_sandbox_refunds_enabled: bool = False
    paypal_resolve_merchant_id: UUID | None = None
    paypal_sandbox_client_id: SecretStr | None = None
    paypal_sandbox_client_secret: SecretStr | None = None
    paypal_sandbox_merchant_id: str | None = None

    @field_validator("database_path", mode="before")
    @classmethod
    def resolve_database_path(cls, value):
        if isinstance(value, str) and (not value.strip() or value == ":memory:"):
            raise ValueError("Use a non-empty local database file path")
        path = Path(value).expanduser()
        return (path if path.is_absolute() else BACKEND_DIR / path).resolve()
