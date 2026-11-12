"""Contracts and validation types for evidence workspace."""

from pydantic import BaseModel
from app.schemas.evidence import EvidenceRefreshResult, PayPalEvidenceFact


class _State(BaseModel):
    check: EvidenceRefreshResult
    facts: list[PayPalEvidenceFact]
