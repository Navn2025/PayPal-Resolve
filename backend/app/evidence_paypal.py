"""Collect seller-scoped read-only PayPal facts for SDK evidence."""

from decimal import Decimal

from .errors import StoreError
from .evidence_models import EvidenceIssue


def issue(kind, detail, *, reference=None, status="missing"):
    return EvidenceIssue(kind=kind, reference=reference, status=status, detail=detail)


def _failure(kind, error, reference=None):
    if error.status_code == 404:
        status = "missing"
    elif (
        error.status_code in (403, 422) or "requires one purchase unit" in error.detail
    ):
        status = "unsupported"
    elif error.status_code == 409:
        status = "mismatch"
    else:
        status = "unavailable"
    return issue(kind, error.detail, reference=reference, status=status)


def _fact(kind, resource, capture_id):
    amount = getattr(resource, "amount", None)
    return {
        "kind": kind,
        "reference": resource.id,
        "status": resource.status,
        "amount": amount.value if amount else None,
        "currency": amount.currency_code if amount else None,
        "capture_id": capture_id,
    }


def collect_paypal(
    client, merchant_id, order_id, capture_id, refund_ids, expected_amount=None
):
    issues, facts = [], []
    if not (order_id or capture_id):
        issues.append(
            issue(
                "paypal_capture",
                "Link a PayPal capture or a completed PayPal order before refreshing.",
            )
        )
        for reference in refund_ids:
            issues.append(
                issue(
                    "paypal_refund",
                    "A seller-scoped capture is needed to verify this refund.",
                    reference=reference,
                )
            )
        return facts, issues, False
    try:
        settings = client._merchant_configuration(merchant_id)
        token = client._access_token(settings)
    except StoreError as error:
        return facts, [_failure("paypal_connection", error)], False

    order = None
    if not capture_id:
        try:
            order = client._order_resource(order_id, token)
            unit = order.purchase_units[0]
            if unit.payee.merchant_id != settings.paypal_sandbox_merchant_id:
                raise StoreError(
                    409,
                    "PayPal order payee does not match the configured Sandbox seller",
                )
            capture_id = unit.payments.captures[0].id
        except StoreError as error:
            return facts, [_failure("paypal_order", error, order_id)], False
    try:
        capture, related_order = client._capture_resource(capture_id, token)
        if expected_amount is not None and expected_amount != capture.amount.value:
            raise StoreError(
                409, "PayPal capture amount does not match the linked Resolve payment"
            )
    except StoreError as error:
        issues.append(_failure("paypal_capture", error, capture_id))
        for reference in refund_ids:
            issues.append(
                issue(
                    "paypal_refund",
                    "The parent capture could not be verified.",
                    reference=reference,
                )
            )
        return facts, issues, False

    facts.append(_fact("paypal_capture", capture, capture.id))
    history = None
    if order_id and related_order and related_order != order_id:
        issues.append(
            issue(
                "paypal_order_reference",
                "The linked order differs from the capture’s related order.",
                reference=order_id,
                status="mismatch",
            )
        )
    elif order_id or related_order:
        order_id = order_id or related_order
        try:
            order = order or client._order_resource(order_id, token)
            history = client._order_refunds(order, capture, token, limit=20)
            facts.append(_fact("paypal_order", order, capture.id))
        except StoreError as error:
            issues.append(_failure("paypal_order", error, order_id))
    else:
        issues.append(
            issue(
                "paypal_order",
                "The capture did not identify its order. Link the PayPal order ID to discover refund history.",
            )
        )

    refunds = {refund.id: refund for refund in history or []}
    for reference in refund_ids:
        if reference in refunds:
            continue
        if history is not None:
            issues.append(
                issue(
                    "paypal_refund",
                    "This refund was not found in the verified order history.",
                    reference=reference,
                )
            )
            continue
        try:
            refunds[reference] = client._refund_resource(
                capture.id, capture.amount.value, reference, token
            )
        except StoreError as error:
            issues.append(_failure("paypal_refund", error, reference))

    reserved = sum(
        (
            r.amount.value
            for r in refunds.values()
            if r.status in ("PENDING", "COMPLETED")
        ),
        Decimal("0"),
    )
    if reserved > capture.amount.value:
        issues.append(
            issue(
                "paypal_refund",
                "The linked refund amounts exceed the verified capture.",
                status="mismatch",
            )
        )
        refunds.clear()
    facts.extend(
        _fact("paypal_refund", refund, capture.id) for refund in refunds.values()
    )
    return facts, issues, history is not None
