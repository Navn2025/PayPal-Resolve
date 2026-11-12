"""Contracts and validation types for ai privacy."""

from pydantic import BaseModel


class InjectionFlag(BaseModel):
    rule_id: str
    label: str
    message_id: str
