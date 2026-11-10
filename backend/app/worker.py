"""Trusted local recovery of already-approved sandbox executions; no new consent."""

import argparse
import json
import time
from datetime import datetime, timedelta, timezone

from .errors import StoreError
from .executions import RECOVERY_WINDOW, SUBMISSION_LEASE, RefundExecutionService
from .paypal import PayPalSandboxClient
from .paypal_history import PayPalHistoryService
from .settings import Settings
from .storage import ResolveStore, configured_store


def _due(row, now):
    age = now - datetime.fromisoformat(row["updated_at"])
    if row["status"] == "reserved":
        # Avoid racing the request handler between reservation and first claim.
        return age >= SUBMISSION_LEASE
    if row["status"] == "submitting":
        return (
            not row["lease_expires_at"]
            or datetime.fromisoformat(row["lease_expires_at"]) <= now
        )
    if row["status"] == "unknown":
        return age >= timedelta(seconds=min(300, 2 ** min(row["attempt_count"], 8)))
    return age >= timedelta(seconds=30)


def run_once(store: ResolveStore, paypal: PayPalSandboxClient, *, limit=20, now=None):
    if not 1 <= limit <= 100:
        raise ValueError("Worker limit must be between 1 and 100")
    merchant_id = paypal.settings.paypal_resolve_merchant_id
    if merchant_id is None:
        raise StoreError(503, "A configured Resolve merchant is required")
    now = now or datetime.now(timezone.utc)
    cutoff = (now - RECOVERY_WINDOW).isoformat(timespec="microseconds")
    with store.transaction() as connection:
        rows = connection.execute(
            """SELECT * FROM refund_executions WHERE merchant_id=? AND
               (status='pending' OR (status IN ('reserved','unknown','submitting') AND created_at>=?))
               ORDER BY updated_at,id LIMIT ?""",
            (str(merchant_id), cutoff, limit * 10),
        ).fetchall()
        needs_review = connection.execute(
            """SELECT count(*) FROM refund_executions WHERE merchant_id=?
               AND status IN ('reserved','unknown','submitting') AND created_at<?""",
            (str(merchant_id), cutoff),
        ).fetchone()[0]
    report = {
        "processed": 0,
        "completed": 0,
        "pending": 0,
        "failed": 0,
        "unconfirmed": 0,
        "blocked": 0,
        "errors": 0,
        "needs_reconciliation": needs_review,
        "results": [],
        "webhooks": PayPalHistoryService(store, paypal).process(
            merchant_id, limit, now=now
        ),
    }
    service = RefundExecutionService(store, paypal)
    for row in rows:
        if report["processed"] >= limit:
            break
        if not _due(row, now):
            continue
        report["processed"] += 1
        item = {"case_id": row["case_id"], "execution_id": row["id"]}
        try:
            result = (
                service.refresh(row["case_id"], row["id"], merchant_id)
                if row["status"] == "pending"
                else service.retry(row["case_id"], row["id"], merchant_id)
            )
            item["status"] = result.status
            key = (
                result.status
                if result.status in ("completed", "pending", "failed")
                else "unconfirmed"
            )
            report[key] += 1
        except StoreError as error:
            report["blocked"] += 1
            item.update(status="blocked", http_status=error.status_code)
        except Exception:
            report["errors"] += 1
            item["status"] = "worker_error"
        report["results"].append(item)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Recover existing approved Resolve sandbox executions"
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--once", action="store_true", help="Run one bounded pass (default)"
    )
    mode.add_argument("--loop", action="store_true", help="Continue until interrupted")
    parser.add_argument("--interval", type=int, default=30)
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args(argv)
    if args.interval < 5 or not 1 <= args.limit <= 100:
        parser.error("Use an interval of at least 5 seconds and a limit of 1-100")
    paypal = None
    try:
        settings = Settings()
        store = configured_store(settings)
        store.initialize()
        while True:
            from .platform_connections import Connections
            with store.transaction() as db:
                owners = {str(r[0]) for r in db.execute("SELECT merchant_id FROM platform_connections WHERE provider='paypal'")}
            if settings.paypal_resolve_merchant_id:
                owners.add(str(settings.paypal_resolve_merchant_id))
            reports = []
            for owner in sorted(owners):
                paypal = PayPalSandboxClient(Connections(store, settings).settings_for(owner))
                try:
                    reports.append({"merchant_id": owner, **run_once(store, paypal, limit=args.limit)})
                finally:
                    paypal.close()
                    paypal = None
            report = {"workspaces": reports, "errors": sum(r["errors"] for r in reports), "processed": sum(r["processed"] for r in reports)}
            print(json.dumps(report), flush=True)
            if not args.loop:
                return 1 if report["errors"] else 0
            time.sleep(args.interval)
    except KeyboardInterrupt:
        return 130
    except Exception:
        print(
            json.dumps(
                {
                    "error": "Worker configuration or storage is unavailable; sensitive details omitted"
                }
            ),
            flush=True,
        )
        return 1
    finally:
        if paypal is not None:
            paypal.close()


if __name__ == "__main__":
    raise SystemExit(main())
