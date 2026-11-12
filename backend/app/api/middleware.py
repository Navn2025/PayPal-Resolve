"""Private response policy and audited request completion."""

from fastapi import FastAPI, Request

from app.services.merchant.audit import record_request_finished


def install_middleware(application: FastAPI, store) -> None:
    @application.middleware("http")
    async def operation_audit(request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        intent = getattr(request.state, "audit_intent", None)
        if intent:
            record_request_finished(
                store,
                request.state.audit_merchant,
                request.state.actor_id,
                intent,
                response.status_code,
            )
        if request.url.path.startswith(("/platform", "/webhooks/zendesk")):
            response.headers.update(
                {"Cache-Control": "private, no-store", "Referrer-Policy": "no-referrer"}
            )
        return response
