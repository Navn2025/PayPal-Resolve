"""Merchant API for AI promise proposals. Proposals are never saved as promises."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

import groq
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from .ai_extraction import (
    ExtractionRequest,
    ExtractionResult,
    ExtractionSettings,
    SkipReason,
    conversation_transcript,
    current_data_policy,
    extract_promises,
)
from .ai_usage import ExtractionUsage
from .auth import CurrentMerchant, Store
from .customer_portal import CustomerPortal
from .next_action import Explanation, collect, explain
from .resolution_workspace import ResolutionWorkspace

router = APIRouter(tags=["AI promise extraction"])


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


def get_ai_settings() -> ExtractionSettings:
    return ExtractionSettings()


def get_data_policy() -> str:
    return current_data_policy()


def get_usage(request: Request) -> ExtractionUsage:
    # One store per application instance, kept in memory (see app.ai_usage).
    state = request.app.state
    if not hasattr(state, "extraction_usage"):
        state.extraction_usage = ExtractionUsage()
    return state.extraction_usage


def get_ai_client(settings: Annotated[ExtractionSettings, Depends(get_ai_settings)]):
    if not settings.enabled or settings.groq_key is None:
        yield None
        return
    client = groq.Groq(
        api_key=settings.groq_key.get_secret_value(),
        timeout=settings.timeout_seconds,
        max_retries=1,
    )
    try:
        yield client
    finally:
        client.close()


@router.post(
    "/resolution-cases/{case_id}/ai/extract-promises",
    response_model=ExtractionResult,
    responses={404: {"description": "Resolution case not found"}},
)
def extract_promise_proposals(
    case_id: UUID,
    store: Store,
    merchant: CurrentMerchant,
    settings: Annotated[ExtractionSettings, Depends(get_ai_settings)],
    client: Annotated[groq.Groq | None, Depends(get_ai_client)],
    data_policy: Annotated[str, Depends(get_data_policy)],
    usage: Annotated[ExtractionUsage, Depends(get_usage)],
    payload: ExtractionRequest | None = None,
):
    """Propose promises for review from the case's customer conversation, or from
    supplied messages. Does not record promises or call PayPal."""
    if payload is not None and payload.messages is not None:
        ResolutionWorkspace(store).get(case_id, merchant.id)
        messages, source = payload.messages, "merchant_supplied"
    else:
        stored = CustomerPortal(store).merchant_messages(case_id, merchant.id)
        messages, source = conversation_transcript(stored), "case_conversation"
    return extract_promises(
        case_id,
        messages,
        client,
        settings,
        source,
        data_policy=data_policy,
        usage=usage,
        merchant_id=merchant.id,
    )


@router.get("/ai/usage", response_model=UsageSummary)
def extraction_usage(
    merchant: CurrentMerchant,
    settings: Annotated[ExtractionSettings, Depends(get_ai_settings)],
    usage: Annotated[ExtractionUsage, Depends(get_usage)],
):
    """Today's (UTC) extraction usage for the authenticated merchant. Counted in this
    API process's memory only: it resets on restart and is not shared between
    processes."""
    summary = usage.summary(merchant.id)
    return UsageSummary(
        **summary,
        daily_token_limit=settings.daily_token_limit,
        remaining_tokens=max(settings.daily_token_limit - summary["tokens"], 0),
    )


@router.post(
    "/resolution-cases/{case_id}/ai/explain-next-action",
    response_model=Explanation,
    responses={404: {"description": "Resolution case not found"}},
)
def explain_next_action(
    case_id: UUID,
    store: Store,
    merchant: CurrentMerchant,
    settings: Annotated[ExtractionSettings, Depends(get_ai_settings)],
    client: Annotated[groq.Groq | None, Depends(get_ai_client)],
    data_policy: Annotated[str, Depends(get_data_policy)],
    usage: Annotated[ExtractionUsage, Depends(get_usage)],
):
    """One-sentence explanation of the next action, written from structured case facts only.

    Uses the extraction switch, data policy, cache, token cap and daily budget. Text whose
    amounts, dates or numbers are not in the facts is replaced by the code template.
    Advisory only: it never approves, submits or records anything."""
    action = collect(case_id, merchant.id, store)
    return explain(action, client, settings, data_policy=data_policy, usage=usage, merchant_id=merchant.id)
