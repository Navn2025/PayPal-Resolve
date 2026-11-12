"""Contracts and validation types for customer google."""

from pydantic import BaseModel, ConfigDict, SecretStr


class GoogleStart(BaseModel):
    authorize_url: str
    browser_token: str


class GoogleFinish(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: SecretStr
    browser_token: SecretStr
    code: SecretStr
