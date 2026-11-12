"""Contracts and validation types for ai routes."""

from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel
from app.schemas.extraction import SkipReason


class UsageCall(BaseModel):
    at: datetime
    case_id: UUID
    tokens: int
    cache_hit: bool
    skipped_reason: SkipReason | None
    status: Literal["ok", "needs_review"]


class UsageSummary(BaseModel):
    date: str
    scope: Literal["process_memory"] = "process_memory"
    tokens: int
    daily_token_limit: int
    remaining_tokens: int
    model_calls: int
    cache_hits: int
    skipped: dict[str, int]
    calls: list[UsageCall]
