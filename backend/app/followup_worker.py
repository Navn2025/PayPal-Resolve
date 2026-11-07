"""Background reads and customer notifications; never submits a refund."""

import argparse
from datetime import datetime, timedelta, timezone
import json
import time
from uuid import uuid4

import httpx

from .customer_email import deliver, enqueue_verified_refunds, mail_config, stamp
from .errors import StoreError
from .paypal import PayPalSandboxClient
from .paypal_history import PayPalHistoryService
from .resolution_workspace import ResolutionWorkspace
from .settings import Settings
from .storage import configured_store


def _claim_refresh(store, merchant, settings, now):
    with store.transaction(write=True) as db:
        row = db.execute(
            """SELECT p.*,CASE WHEN s.revision=p.revision THEN s.failures ELSE 0 END AS failures
               FROM resolution_promises p LEFT JOIN provider_refresh_schedule s ON s.promise_id=p.id
               WHERE p.merchant_id=? AND (s.promise_id IS NULL OR s.revision!=p.revision OR s.next_attempt_at<=?)
               AND ((? AND (p.kind='replacement' OR
                     (p.kind='return' AND json_extract(p.promise_json,'$.target.milestone')='carrier_delivered')))
                 OR (? AND (
                     (p.kind='order_cancellation' AND json_extract(p.promise_json,'$.target.shopify_order_id') IS NOT NULL
                      AND (json_extract(p.promise_json,'$.target.paypal_authorization_id') IS NULL OR ?))
                     OR (p.kind='store_credit_or_exchange' AND json_extract(p.promise_json,'$.target.action')='exchange'))))
               ORDER BY COALESCE(s.next_attempt_at,p.created_at),p.id LIMIT 1""",
            (
                str(merchant),
                stamp(now),
                bool(settings.easypost_api_key),
                bool(settings.shopify_shop_domain and settings.shopify_admin_token),
                settings.paypal_sandbox_enabled,
            ),
        ).fetchone()
        if not row:
            return None
        lease = str(uuid4())
        db.execute(
            """INSERT INTO provider_refresh_schedule VALUES (?,?,?,?,?) ON CONFLICT(promise_id)
               DO UPDATE SET revision=excluded.revision,next_attempt_at=excluded.next_attempt_at,
               failures=excluded.failures,lease_id=excluded.lease_id""",
            (
                row["id"],
                row["revision"],
                stamp(now + timedelta(minutes=3)),
                row["failures"],
                lease,
            ),
        )
        return row, lease


def refresh_due(store, paypal, settings, *, now, limit):
    merchant = (
        settings.resolution_connector_merchant_id or settings.paypal_resolve_merchant_id
    )
    counts = {"checked": 0, "failed": 0}
    if not settings.auto_provider_refresh_enabled or not merchant:
        return counts
    workspace = ResolutionWorkspace(store)
    for _ in range(limit):
        claim = _claim_refresh(store, merchant, settings, now)
        if not claim:
            break
        row, lease = claim
        failures = 0
        try:
            result = workspace.refresh(
                row["resolution_id"],
                row["id"],
                merchant,
                paypal,
                row["revision"],
                automatic=True,
            )
            interval = 3600 if result.outcome == "fulfilled" else 300
            counts["checked"] += 1
        except StoreError:
            failures = row["failures"] + 1
            interval = min(3600, 60 * 2 ** min(failures, 6))
            counts["failed"] += 1
        with store.transaction(write=True) as db:
            db.execute(
                """UPDATE provider_refresh_schedule SET next_attempt_at=?,failures=?,lease_id=NULL
                   WHERE promise_id=? AND revision=? AND lease_id=?""",
                (
                    stamp(now + timedelta(seconds=interval)),
                    failures,
                    row["id"],
                    row["revision"],
                    lease,
                ),
            )
    return counts


def run_once(store, paypal, settings, mail_http, *, limit=20, now=None):
    if not 1 <= limit <= 100:
        raise ValueError("Use a limit of 1–100")
    delivery_clock = now
    now = now or datetime.now(timezone.utc)
    paypal_result = None
    if (
        settings.paypal_sandbox_enabled
        and settings.paypal_sandbox_webhook_id
        and settings.paypal_resolve_merchant_id
    ):
        paypal_result = PayPalHistoryService(store, paypal).process(
            settings.paypal_resolve_merchant_id, limit, now=now
        )
    mail = None
    if settings.customer_email_enabled:
        mail_config(settings)
        with store.transaction(write=True) as db:
            db.execute(
                "DELETE FROM customer_sessions WHERE expires_at<=?", (stamp(now),)
            )
            db.execute(
                "DELETE FROM customer_signins WHERE created_at<=?",
                (stamp(now - timedelta(days=1)),),
            )
        queued = enqueue_verified_refunds(store, now, limit)
        mail = {
            "new_refund_notices": queued,
            **deliver(store, settings, mail_http, limit=limit, now=delivery_clock),
        }
    return {
        "paypal": paypal_result,
        "provider_checks": refresh_due(store, paypal, settings, now=now, limit=limit),
        "mail": mail,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval", type=int, default=30)
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args(argv)
    if args.interval < 5 or not 1 <= args.limit <= 100:
        parser.error("Use an interval of at least 5 seconds and a limit of 1–100")
    try:
        settings = Settings()
        store = configured_store(settings)
        store.initialize()
        paypal = PayPalSandboxClient(settings)
        try:
            with httpx.Client(
                trust_env=False, timeout=10, follow_redirects=False
            ) as client:
                while True:
                    try:
                        print(
                            json.dumps(
                                run_once(
                                    store, paypal, settings, client, limit=args.limit
                                )
                            ),
                            flush=True,
                        )
                    except (StoreError, ValueError):
                        print(
                            json.dumps(
                                {
                                    "error": "Follow-up worker configuration or storage is unavailable"
                                }
                            ),
                            flush=True,
                        )
                        if not args.loop:
                            return 1
                    if not args.loop:
                        return 0
                    time.sleep(args.interval)
        finally:
            paypal.close()
    except KeyboardInterrupt:
        return 130
    except Exception:
        print(
            json.dumps(
                {"error": "Follow-up worker could not run; sensitive details omitted"}
            ),
            flush=True,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
