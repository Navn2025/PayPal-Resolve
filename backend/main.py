"""Compatibility ASGI entry point; prefer ``uvicorn app.main:app``."""

from app.main import app as app, create_app as create_app
