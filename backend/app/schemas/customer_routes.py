"""Contracts and validation types for customer routes."""

from pydantic import BaseModel


class CustomerAccountCapabilities(BaseModel):
    email_enabled: bool
    google_enabled: bool
