"""Advisory investigation contracts. No execution instruction is representable."""

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field

from app.schemas.resolution import Input


IssueStatus = Literal[
    "confirmed_full_refund",
    "partial_refund",
    "pending_refund",
    "approval_unconfirmed",
    "contradictory",
    "stale",
    "missing",
]
NextStep = Literal[
    "review", "request_evidence", "wait_provider", "no_action", "abstain"
]


class ReadSelection(Input):
    operation: Literal["refresh_linked_capture", "refresh_linked_refund"]
    evidence_id: UUID


class Triage(Input):
    issue_type: Literal["refund", "unknown"]
    escalate: bool = Field(strict=True)
    reads: list[ReadSelection] = Field(max_length=1)


class Recommendation(Input):
    status: IssueStatus
    evidence_ids: list[UUID] = Field(max_length=64)
    next_step: NextStep


class Finding(Input):
    evidence_id: UUID
    source: Literal["provider_fact", "merchant_claim", "system"]
    kind: str
    status: str
    amount: str | None = None
    currency: str | None = None
    verified_at: AwareDatetime | None = None


class InvestigationResult(Input):
    issue_type: Literal["refund", "unknown"]
    status: IssueStatus
    findings: list[Finding]
    contradictions: list[str]
    missing_evidence: list[str]
    next_step: NextStep
    reason: str
    validation_failures: list[str] = Field(default_factory=list)
    last_verified_at: AwareDatetime | None = None
    evidence_fresh_until: AwareDatetime | None = None
    evidence_snapshot: str
    case_revision: int
    model_calls: list[dict] = Field(default_factory=list)


class InvestigationReview(Input):
    expected_revision: int = Field(gt=0, strict=True)
    evidence_snapshot: str = Field(pattern=r"^[a-f0-9]{64}$")
    decision: Literal["approve", "reject", "request_evidence"]


class ReviewReceipt(InvestigationReview):
    reviewer_merchant_id: UUID
    reviewer_identity: str
    reviewed_at: AwareDatetime
    authorizes_payment: Literal[False] = False


class InvestigationView(Input):
    id: UUID
    case_id: UUID
    case_revision: int
    state: Literal["queued", "running", "finished", "blocked"]
    stale: bool
    created_at: AwareDatetime
    completed_at: AwareDatetime | None = None
    result: InvestigationResult | None = None
    review: ReviewReceipt | None = None


class InvestigationPage(Input):
    items: list[InvestigationView]
