"""Process signed support imports and daily promise alerts; never executes money or sends email."""

import argparse
import json
import time

import httpx

from app.services.merchant.imports import process_jobs
from app.services.merchant.operations import Operations
from app.core.config import Settings
from app.repositories.factory import configured_store


def run_once(store, settings, http, limit=20):
    result = process_jobs(store, settings, http, limit)
    with store.transaction() as db:
        merchants = [
            r[0]
            for r in db.execute("SELECT DISTINCT merchant_id FROM resolution_cases")
        ]
    for merchant in merchants:
        Operations(store).scan(merchant)
    from app.services.commerce.events import Events

    with store.transaction() as db:
        scopes = [
            (r[0], r[1])
            for r in db.execute(
                "SELECT DISTINCT merchant_id,source FROM commerce_orders WHERE resolution_id IS NOT NULL"
            )
        ]
    reconciled = sum(
        Events(store).reconcile(merchant, source) for merchant, source in scopes
    )
    return {
        **result,
        "workspaces_scanned": len(merchants),
        "app_orders_reconciled": reconciled,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval", type=int, default=60)
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    if args.interval < 10 or not 1 <= args.limit <= 100:
        parser.error("Use interval >=10 and limit 1-100")
    settings = Settings()
    store = configured_store(settings)
    store.initialize()
    with httpx.Client(timeout=15, trust_env=False, follow_redirects=False) as http:
        while True:
            print(json.dumps(run_once(store, settings, http, args.limit)), flush=True)
            if not args.loop:
                break
            time.sleep(args.interval)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
