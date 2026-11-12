"""Compare an app snapshot only with facts from an applicable PayPal check."""

from datetime import datetime
from decimal import Decimal

from app.schemas.commerce import (
    CommerceFieldCheck,
    CommerceProviderIssue,
    CommerceReport,
    CommerceSnapshot,
)

_CAPTURE_STATES = {
    "COMPLETED": "completed",
    "PARTIALLY_REFUNDED": "partially_refunded",
    "REFUNDED": "refunded",
    "PENDING": "pending",
    "DECLINED": "failed",
    "FAILED": "failed",
}


def snapshot_row(db, case):
    return db.execute(
        """SELECT resolution_id,source,order_reference,revision,snapshot_json,synced_at
           FROM commerce_orders WHERE resolution_id=? AND merchant_id=?""",
        (case["id"], case["merchant_id"]),
    ).fetchone()


def commerce_report(db, case, summary):
    row = snapshot_row(db, case)
    if row is None:
        return None
    app = CommerceSnapshot.model_validate_json(row["snapshot_json"])
    synced_at = datetime.fromisoformat(row["synced_at"])
    checked = summary.last_checked_at
    started = summary.last_check_started_at
    applies = started is not None and started >= synced_at
    facts = {
        fact.kind: fact
        for fact in summary.verified
        if applies and fact.checked_at == checked
    }
    order = facts.get("paypal_order")
    capture = facts.get("paypal_capture")
    payment = app.payment
    checks = []

    def check(
        field, app_value, provider_value, when=None, *, conflicting_reference=False
    ):
        def as_text(value):
            return format(value, ".2f") if isinstance(value, Decimal) else value

        app_value = as_text(app_value)
        provider_value = as_text(provider_value)
        checks.append(
            CommerceFieldCheck(
                field=field,
                app_value=app_value,
                paypal_value=provider_value,
                status=(
                    "mismatch"
                    if conflicting_reference
                    else "unverified"
                    if provider_value is None
                    else "missing_app"
                    if app_value is None
                    else "match"
                    if app_value == provider_value
                    else "mismatch"
                ),
                checked_at=when,
            )
        )

    when = capture.checked_at if capture else None
    app_order = payment.paypal_order_id if payment else None
    bad_order = bool(
        when
        and app_order
        and any(
            item.kind == "paypal_order_reference"
            and item.status == "mismatch"
            and item.reference == app_order
            for item in summary.issues
        )
    )
    check(
        "paypal_order_id",
        app_order,
        order.reference if order else None,
        order.checked_at if order else when if bad_order else None,
        conflicting_reference=bad_order,
    )
    check(
        "paypal_capture_id",
        payment.paypal_capture_id if payment else None,
        capture.reference if capture else None,
        when,
    )
    check(
        "currency",
        payment.currency if payment else None,
        capture.currency if capture else None,
        when,
    )
    check(
        "payment_status",
        payment.status if payment else None,
        _CAPTURE_STATES.get(capture.status) if capture else None,
        when,
    )
    check(
        "captured_amount",
        payment.captured_amount if payment else None,
        capture.amount if capture else None,
        when,
    )
    full_history = (
        capture is not None and order is not None and summary.order_history_verified
    )
    check(
        "refunded_amount",
        payment.refunded_amount if payment else None,
        summary.provider_completed_amount if full_history else None,
        when if full_history else None,
    )
    issues = [
        CommerceProviderIssue.model_validate(item.model_dump())
        for item in summary.issues
        if item.kind != "refund_confirmation"
    ]
    if checked is not None and not applies:
        issues = [
            CommerceProviderIssue(
                kind="provider_refresh",
                status="missing",
                detail="Refresh PayPal after syncing this app revision.",
            )
        ]
    status = (
        "mismatch"
        if any(item.status == "mismatch" for item in checks)
        else "match"
        if all(item.status == "match" for item in checks)
        else "incomplete"
    )
    return CommerceReport(
        case_id=case["id"],
        app=app,
        synced_at=synced_at,
        status=status,
        checks=checks,
        last_checked_at=checked,
        provider_issues=issues,
    )
