"""Request-scoped provider selection, honoring injected clients and workspace scope."""

from app.repositories.merchant_queries import has_connection


def settings_for(request, merchant):
    from app.services.merchant.connections import Connections

    return Connections(
        request.app.state.store, request.app.state.settings
    ).settings_for(merchant)


def paypal_for(request, merchant):
    from app.services.merchant.connections import Connections

    if not has_connection(request.app.state.store, merchant):
        return request.app.state.paypal_client
    from app.integrations.paypal.client import PayPalSandboxClient

    connections = Connections(request.app.state.store, request.app.state.settings)
    return PayPalSandboxClient(
        connections.settings_for(merchant), request.app.state.followup_http
    )
