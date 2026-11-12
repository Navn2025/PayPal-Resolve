"""Persist request completion using the existing merchant audit contract."""

from app.services.merchant.identity import audit


def record_request_finished(store, merchant_id, actor_id, intent, status: int) -> None:
    with store.transaction(write=True) as connection:
        audit(
            connection, merchant_id, actor_id, "request_finished", intent, status=status
        )
