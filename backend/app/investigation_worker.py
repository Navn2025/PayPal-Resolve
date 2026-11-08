"""Separate bounded investigation worker; never starts the execution worker."""

import argparse
import json
import time

import httpx

from .inference import InvestigationSettings
from .investigations import Investigations
from .investigation_refresh import refresh_linked
from .paypal import PayPalSandboxClient
from .settings import Settings
from .storage import configured_store


def run_once(
    store, *, settings=None, limit=20, groq=None, openrouter=None, refresh=None
):
    if not 1 <= limit <= 100:
        raise ValueError("Use a worker limit of 1-100")
    service = Investigations(store, settings)
    processed = 0
    for _ in range(limit):
        if not service.run_one(groq, openrouter, refresh):
            break
        processed += 1
    return {"processed": processed}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--interval", type=int, default=10)
    args = parser.parse_args()
    if args.interval < 5 or not 1 <= args.limit <= 100:
        parser.error("Use interval >=5 and limit 1-100")
    # Explicit environment injection only. No local .env file is read by this worker.
    cfg = Settings(_env_file=None)
    ai = InvestigationSettings()
    store = configured_store(cfg)
    store.initialize()
    with httpx.Client(trust_env=False, follow_redirects=False, timeout=8) as http:
        paypal = PayPalSandboxClient(cfg, http)
        refresh = lambda case, merchant, selection: refresh_linked(
            store, paypal, case, merchant, selection
        )
        while True:
            print(
                json.dumps(
                    run_once(store, settings=ai, limit=args.limit, refresh=refresh)
                ),
                flush=True,
            )
            if not args.loop:
                return
            time.sleep(args.interval)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception:
        print('{"error":"Investigation worker unavailable; sensitive details omitted"}')
        raise SystemExit(1)
