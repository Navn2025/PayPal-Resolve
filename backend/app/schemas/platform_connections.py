"""Contracts and validation types for platform connections."""

from pydantic import Field, SecretStr
from app.schemas.identity import Input


class ConnectionInput(Input):
    expected_revision: int = Field(ge=0)
    enabled: bool = False
    config: dict[str, str | bool] = Field(default_factory=dict, max_length=6)
    credentials: dict[str, SecretStr] = Field(default_factory=dict, max_length=4)
