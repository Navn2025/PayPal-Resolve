"""Resolve a capability-scoped buyer order before exposing aftercare actions."""

from app.core.exceptions import StoreError
from app.repositories.commerce_queries import order_for_resolution
from app.schemas.aftercare import OrderLocator
from app.services.customer.portal import CustomerPortal


def buyer_order(store, token):
    with store.transaction() as connection:
        link = CustomerPortal._authorized_link(connection, token)
        row = order_for_resolution(
            connection, link["merchant_id"], link["resolution_id"]
        )
        if not row:
            raise StoreError(404, "This case has no connected app order")
        return link, OrderLocator(
            source=row["source"], order_reference=row["order_reference"]
        )
