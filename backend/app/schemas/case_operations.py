"""Contracts and validation types for case operations."""

from datetime import datetime
from typing import Literal
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from app.schemas.resolution import ResolutionView

Workflow = Literal[
    "waiting_on_customer",
    "needs_approval",
    "pending_with_paypal",
    "merchant_action",
    "resolved",
]

NextActor = Literal["customer", "merchant", "paypal", "none"]


class Operations(BaseModel):
    revision: int
    assignee: str | None
    due_at: datetime | None
    promise_due_at: datetime | None
    overdue: bool
    waiting_on_customer: bool
    workflow: Workflow
    next_actor: NextActor
    next_action: str
    unread_count: int
    message_watermark: int
    issue_type: str | None


class OperationsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_revision: int = Field(ge=0)
    assignee: str | None = Field(default=None, min_length=1, max_length=80)
    due_at: AwareDatetime | None = None
    waiting_on_customer: bool = False


class MarkRead(BaseModel):
    model_config = ConfigDict(extra="forbid")
    through: int = Field(ge=0, le=2**53 - 1)


class InboxItem(ResolutionView):
    operations: Operations


class InboxPage(BaseModel):
    items: list[InboxItem]
    total: int
    limit: int
    offset: int
