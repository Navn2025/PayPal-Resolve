"""ASGI entry point. Application composition lives in app.application."""

from app.application import create_app as create_app

app = create_app()
