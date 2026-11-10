from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import SecretStr, field_validator
from uuid import UUID
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RESOLVE_",
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    database_path: Path = BACKEND_DIR / "data" / "resolve.sqlite3"
    database_url: SecretStr | None = None
    merchant_web_origin: str | None = None
    paypal_login_enabled: bool = False
    paypal_login_environment: Literal["sandbox", "live"] = "sandbox"
    paypal_login_client_id: SecretStr | None = None
    paypal_login_client_secret: SecretStr | None = None
    paypal_sandbox_enabled: bool = False
    paypal_sandbox_refunds_enabled: bool = False
    paypal_sandbox_partial_refunds_enabled: bool = False
    paypal_sandbox_webhook_id: str | None = None
    paypal_resolve_merchant_id: UUID | None = None
    paypal_sandbox_client_id: SecretStr | None = None
    paypal_sandbox_client_secret: SecretStr | None = None
    paypal_sandbox_merchant_id: str | None = None
    resolution_connector_merchant_id: UUID | None = None
    shopify_shop_domain: str | None = None
    shopify_admin_token: SecretStr | None = None
    easypost_api_key: SecretStr | None = None
    auto_provider_refresh_enabled: bool = False
    customer_email_enabled: bool = False
    customer_email_transport: Literal["resend", "smtp"] = "resend"
    customer_email_merchant_id: UUID | None = None
    customer_public_origin: str | None = None
    customer_signing_key: SecretStr | None = None
    resend_api_key: SecretStr | None = None
    resend_from: str | None = None
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_secure: bool = False
    smtp_user: str | None = None
    smtp_password: SecretStr | None = None
    smtp_from: str | None = None
    customer_google_enabled: bool = False
    google_client_id: SecretStr | None = None
    google_client_secret: SecretStr | None = None
    helpdesk_merchant_id: UUID | None = None
    zendesk_subdomain: str | None = None
    zendesk_oauth_token: SecretStr | None = None
    platform_encryption_key: SecretStr | None = None
    merchant_signup_enabled: bool = True

    @field_validator("database_path", mode="before")
    @classmethod
    def resolve_database_path(cls, value):
        if isinstance(value, str) and (not value.strip() or value == ":memory:"):
            raise ValueError("Use a non-empty local database file path")
        path = Path(value).expanduser()
        return (path if path.is_absolute() else BACKEND_DIR / path).resolve()

    @field_validator("database_url")
    @classmethod
    def postgres_url(cls, value):
        if value is None or not value.get_secret_value().strip():
            return None
        try:
            url = urlsplit(value.get_secret_value())
            valid = (
                url.scheme in ("postgresql", "postgres")
                and url.hostname
                and url.path not in ("", "/")
                and not url.fragment
            )
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("Use a PostgreSQL connection URL with a database name")
        return value
