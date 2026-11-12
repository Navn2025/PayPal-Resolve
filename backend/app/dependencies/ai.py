"""Request-scoped extraction configuration, usage and client cleanup."""

from typing import Annotated
import groq
from fastapi import Depends, Request
from app.core.extraction_config import ExtractionSettings
from app.services.ai.extraction import current_data_policy
from app.services.ai.usage import ExtractionUsage


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
