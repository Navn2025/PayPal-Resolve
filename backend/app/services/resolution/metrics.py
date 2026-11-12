"""Time to verified resolution, read from a case timeline.

Start: the first `promise_recorded` event for the promise. End: the first moment the
PayPal-verified refunds on the linked payment (latest status per refund ID, COMPLETED only)
add up to the promised amount. Merchant-recorded refunds never count.
"""

from datetime import datetime, timedelta
from decimal import Decimal
from math import ceil
from statistics import median

from app.schemas.resolution import ResolutionTimeline

VERIFIED_EVENT = "paypal.refund_verified"


def _time(value) -> datetime:
    return value if isinstance(value, datetime) else datetime.fromisoformat(str(value))


def time_to_verified_resolution(
    timeline: ResolutionTimeline, promise_id, promised: Decimal
) -> timedelta | None:
    starts = [
        _time(item.recorded_at)
        for item in timeline.items
        if str(item.promise_id) == str(promise_id)
        and item.event_type == "promise_recorded"
    ]
    if not starts:
        return None
    start = min(starts)
    latest: dict[str, tuple[str, Decimal]] = {}
    for entry in sorted(
        (e for e in timeline.refund_items if e.event_type == VERIFIED_EVENT),
        key=lambda e: (_time(e.occurred_at), e.id),
    ):
        latest[entry.data["refund_id"]] = (
            entry.data["provider_status"],
            Decimal(str(entry.data["amount"])),
        )
        confirmed = sum(
            (amount for status, amount in latest.values() if status == "COMPLETED"),
            Decimal(0),
        )
        if confirmed >= promised:
            return max(_time(entry.occurred_at) - start, timedelta(0))
    return None


def percentile(values: list[float], share: float) -> float | None:
    """Nearest-rank percentile; None for an empty list."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(ceil(share * len(ordered)) - 1, 0)]


def summarize_hours(durations: list[timedelta | None]) -> dict:
    hours = [item.total_seconds() / 3600 for item in durations if item is not None]
    return {
        "cases": len(durations),
        "resolved": len(hours),
        "unresolved": len(durations) - len(hours),
        "median_hours": round(median(hours), 2) if hours else None,
        "p90_hours": round(percentile(hours, 0.9), 2) if hours else None,
    }
