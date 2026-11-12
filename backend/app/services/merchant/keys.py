"""Integration key policy; issue, support-grant and audit remain one transaction."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from app.core.exceptions import StoreError
from app.repositories import merchant_queries
from app.schemas.aftercare import SupportKeyInput, SupportKeyReceipt
from app.schemas.payments import MerchantIdentity
from app.services.merchant.identity import audit, now

if TYPE_CHECKING:
    from app.repositories.base import ResolveStore


class IntegrationKeys:
    def __init__(self, store: ResolveStore):
        self.store = store

    @staticmethod
    def _require_capacity(connection, merchant_id: UUID) -> None:
        if merchant_queries.active_key_count(connection, merchant_id) >= 25:
            raise StoreError(409, "Revoke an unused SDK key first")

    def issue(self, merchant: MerchantIdentity, actor: str) -> dict:
        with self.store.transaction(write=True) as connection:
            self._require_capacity(connection, merchant.id)
            issued = self.store._issue_key(connection, merchant, "commerce")
            audit(connection, merchant.id, actor, "sdk_key_issued", issued.key_id)
            return {"key_id": issued.key_id, "api_key": issued.api_key}

    def issue_support(
        self, merchant: MerchantIdentity, actor: str, payload: SupportKeyInput
    ) -> SupportKeyReceipt:
        with self.store.transaction(write=True) as connection:
            self._require_capacity(connection, merchant.id)
            issued = self.store._issue_key(connection, merchant, "commerce")
            merchant_queries.add_support_grant(
                connection, issued.key_id, merchant.id, payload.source, now()
            )
            audit(
                connection,
                merchant.id,
                actor,
                "support_key_issued",
                issued.key_id,
                source=payload.source,
            )
            return SupportKeyReceipt(
                key_id=issued.key_id,
                api_key=issued.api_key,
                source=payload.source,
                capabilities=["order_sync", "customer_support"],
            )

    def revoke(self, merchant: MerchantIdentity, actor: str, key_id: UUID) -> dict:
        with self.store.transaction(write=True) as connection:
            row = merchant_queries.find_commerce_key(connection, key_id, merchant.id)
            if not row:
                raise StoreError(404, "SDK key not found")
            merchant_queries.revoke_key(connection, row["id"], now())
            audit(connection, merchant.id, actor, "sdk_key_revoked", row["id"])
        return {"revoked": True}
