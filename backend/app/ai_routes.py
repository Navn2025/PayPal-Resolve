"""Merchant API for AI promise proposals. Proposals are never saved as promises."""

from typing import Annotated
from uuid import UUID

import groq
from fastapi import APIRouter, Depends

from .ai_extraction import (
    AISettings,
    ExtractionRequest,
    ExtractionResult,
    conversation_transcript,
    current_data_policy,
    extract_promises,
)
from .auth import CurrentMerchant, Store
from .customer_portal import CustomerPortal
from .resolution_workspace import ResolutionWorkspace

router = APIRouter(prefix="/resolution-cases", tags=["AI promise extraction"])


def get_ai_settings() -> AISettings:
    return AISettings()


def get_data_policy() -> str:
    return current_data_policy()


def get_ai_client(settings: Annotated[AISettings, Depends(get_ai_settings)]):
    if settings.groq_api_key is None:
        yield None
        return
    client = groq.Groq(
        api_key=settings.groq_api_key.get_secret_value(),
        timeout=settings.resolve_extraction_timeout_seconds,
        max_retries=1,
    )
    try:
        yield client
    finally:
        client.close()


@router.post(
    "/{case_id}/ai/extract-promises",
    response_model=ExtractionResult,
    responses={404: {"description": "Resolution case not found"}},
)
def extract_promise_proposals(
    case_id: UUID,
    store: Store,
    merchant: CurrentMerchant,
    settings: Annotated[AISettings, Depends(get_ai_settings)],
    client: Annotated[groq.Groq | None, Depends(get_ai_client)],
    data_policy: Annotated[str, Depends(get_data_policy)],
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
        case_id, messages, client, settings, source, data_policy=data_policy
    )
