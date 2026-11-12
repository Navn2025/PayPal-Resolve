"""Contracts and validation types for platform imports."""

from uuid import UUID
from pydantic import Field
from app.schemas.identity import Input


class TicketImport(Input):
    ticket_id: int = Field(gt=0, le=2**53 - 1, strict=True)


class ImportMatch(Input):
    case_id: UUID
