"""Contracts and validation types for helpdesk."""

from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class TicketInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticket_id: int = Field(gt=0, le=2**53 - 1, strict=True)


class LinkedTicket(BaseModel):
    ticket_id: int
    status: str
    checked_at: datetime
    url: str


class HelpdeskState(BaseModel):
    configured: bool
    ticket: LinkedTicket | None
