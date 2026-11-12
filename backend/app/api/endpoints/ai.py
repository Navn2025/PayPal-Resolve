"""Merchant API for AI promise proposals. Proposals are never saved as promises."""

from app.dependencies.ai import (
    get_ai_settings as get_ai_settings,
    get_data_policy as get_data_policy,
    get_usage as get_usage,
    get_ai_client as get_ai_client,
)


from app.schemas.ai_usage import (
    UsageCall as UsageCall,
    UsageSummary as UsageSummary,
)


from typing import Annotated
from uuid import UUID

import groq as groq
from fastapi import APIRouter, Depends, Request

from app.schemas.extraction import ExtractionRequest, ExtractionResult
from app.core.extraction_config import ExtractionSettings
from app.services.ai.extraction import conversation_transcript, extract_promises
from app.services.ai.usage import ExtractionUsage
from app.dependencies.auth import CurrentMerchant, Store
from app.services.customer.portal import CustomerPortal
from app.schemas.next_action import Explanation
from app.services.resolution.next_action import collect, explain
from app.schemas.remedies import RemedyRanking
from app.services.resolution.remedies import rank, suggest
from app.services.resolution.workspace import ResolutionWorkspace

router = APIRouter(tags=["AI promise extraction"])


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
        from app.services.merchant.imports import imported_transcript

        messages = (messages + imported_transcript(store, case_id, merchant.id))[-200:]
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
    return explain(
        action,
        client,
        settings,
        data_policy=data_policy,
        usage=usage,
        merchant_id=merchant.id,
    )


@router.post(
    "/resolution-cases/{case_id}/ai/rank-remedies",
    response_model=RemedyRanking,
    responses={404: {"description": "Resolution case not found"}},
)
def rank_remedies(
    case_id: UUID,
    request: Request,
    store: Store,
    merchant: CurrentMerchant,
    settings: Annotated[ExtractionSettings, Depends(get_ai_settings)],
    client: Annotated[groq.Groq | None, Depends(get_ai_client)],
    data_policy: Annotated[str, Depends(get_data_policy)],
    usage: Annotated[ExtractionUsage, Depends(get_usage)],
):
    """Classify the issue and buyer preference, rank the code-built remedy options with a
    one-line reason each, and draft a buyer message, from the masked conversation.

    Uses the extraction switch, data policy, cache, token cap and daily budget. Any option,
    amount or number outside the listed options falls back to code order and a template.
    Advisory only: it never records promises, publishes offers or refunds."""
    suggestions = suggest(
        case_id,
        merchant.id,
        store,
        request.app.state.settings.remedy_partial_refund_percent,
    )
    stored = CustomerPortal(store).merchant_messages(case_id, merchant.id)
    from app.services.merchant.imports import imported_transcript

    messages = (
        conversation_transcript(stored)
        + imported_transcript(store, case_id, merchant.id)
    )[-200:]
    return rank(
        case_id,
        suggestions,
        messages,
        client,
        settings,
        data_policy=data_policy,
        usage=usage,
        merchant_id=merchant.id,
    )
