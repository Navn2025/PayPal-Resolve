"""Contracts and validation types for merchant auth routes."""

from pydantic import BaseModel


class Capabilities(BaseModel):
    paypal_enabled: bool
    paypal_environment: str | None
