"""Contracts and validation types for customer progress."""

from datetime import datetime
from typing import Literal
from pydantic import BaseModel
from app.schemas.case_operations import NextActor


class CustomerMilestone(BaseModel):
    label: str
    occurred_at: datetime
    source: Literal[
        "merchant_recorded", "provider_confirmed", "customer_submitted", "resolve"
    ]


class CustomerNextStep(BaseModel):
    actor: NextActor
    action: str
    due_at: datetime | None
    overdue: bool
