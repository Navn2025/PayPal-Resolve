"""Run the shop and a disposable or persistent local Resolve Sandbox workspace."""

import argparse
from contextlib import nullcontext
from http.cookiejar import CookieJar
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Thread
from time import monotonic, sleep
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPCookieProcessor, ProxyHandler, Request, build_opener
from uuid import UUID, uuid4

from dotenv import dotenv_values
import uvicorn

REPO = Path(__file__).resolve().parents[3]
SHOP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

from app.main import create_app
from app.settings import Settings
from app.storage import SQLiteStore
from app.platform_identity import audit, now


def sandbox_values():
    local = dotenv_values(REPO / "backend" / ".env", interpolate=False)
    fields = (
        "RESOLVE_PAYPAL_SANDBOX_CLIENT_ID",
        "RESOLVE_PAYPAL_SANDBOX_CLIENT_SECRET",
        "RESOLVE_PAYPAL_SANDBOX_MERCHANT_ID",
    )
    values = tuple(os.environ.get(field) or local.get(field) for field in fields)
    if not all(values):
        raise RuntimeError(
            "Set the three PayPal Sandbox credentials in backend/.env first."
        )
    return values


def checkout_smoke(base):
    browser = build_opener(ProxyHandler({}), HTTPCookieProcessor(CookieJar()))
    with browser.open(base + "/api/catalog", timeout=5) as reply:
        if not json.load(reply)["checkoutEnabled"]:
            raise RuntimeError("Store checkout is disabled.")
    payload = json.dumps(
        {"requestId": str(uuid4()), "items": [{"id": "brush", "quantity": 1}]}
    ).encode()
    request = Request(
        base + "/api/orders", data=payload, headers={"Content-Type": "application/json"}
    )
    try:
        with browser.open(request, timeout=32) as reply:
            checkout = json.load(reply)
    except HTTPError as error:
        detail = json.load(error).get("message", "Sandbox order request failed.")
        raise RuntimeError(detail) from None
    if (
        checkout["state"] != "awaiting_approval"
        or checkout["total"] != "8.00"
        or urlsplit(checkout["approvalUrl"]).hostname
        not in {"sandbox.paypal.com", "www.sandbox.paypal.com"}
    ):
        raise RuntimeError(
            "The Sandbox response did not contain the expected pending order."
        )
    print(
        "Genuine PayPal Sandbox order created at USD 8.00; no buyer approval or capture attempted."
    )


def serve(folder, port, smoke):
    client, secret, seller = sandbox_values()
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Install Node.js 24 before starting the shop.")
    if not (
        SHOP / "node_modules" / "@resolve-paypal" / "sdk" / "dist" / "index.js"
    ).is_file():
        raise RuntimeError("Build the Resolve SDK and run npm ci in the shop first.")
    folder.mkdir(parents=True, exist_ok=True)
    store = SQLiteStore(folder / "resolve-sandbox.sqlite3")
    store.initialize()
    with store.transaction() as db:
        row = db.execute(
            "SELECT id FROM merchants WHERE name=?", ("Field Brew Sandbox",)
        ).fetchone()
    if row:
        merchant = UUID(row["id"])
    else:
        initial = store.create_merchant("Field Brew Sandbox")
        merchant = initial.merchant.id
        store.revoke_key(initial.key_id)
    issued = store.issue_key(merchant, scope="commerce")
    with store.transaction(write=True) as db:
        db.execute("INSERT INTO aftercare_apps VALUES (?,?,?,?)", (str(issued.key_id), str(merchant), "field-brew-store", now()))
        audit(db, merchant, "local_sandbox_launcher", "support_key_issued", issued.key_id, source="field-brew-store")
    settings = Settings(
        _env_file=None,
        database_url=None,
        paypal_sandbox_enabled=True,
        paypal_sandbox_refunds_enabled=False,
        paypal_sandbox_partial_refunds_enabled=False,
        paypal_sandbox_client_id=client,
        paypal_sandbox_client_secret=secret,
        paypal_sandbox_merchant_id=seller,
        paypal_resolve_merchant_id=merchant,
    )
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(settings=settings, store=store),
            log_level="warning",
            access_log=False,
        )
    )
    thread = None
    child = None
    listener = socket.socket()
    try:
        listener.bind(("127.0.0.1", 0))
        api = "http://127.0.0.1:" + str(listener.getsockname()[1])
        thread = Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        end = monotonic() + 20
        while not server.started and thread.is_alive() and monotonic() < end:
            sleep(0.1)
        if not server.started:
            raise RuntimeError("Local Resolve Sandbox API did not start.")
        env = {
            name: value
            for name, value in os.environ.items()
            if not name.upper().startswith(("SHOP_", "RESOLVE_"))
        }
        env.update(
            SHOP_PORT=str(port),
            SHOP_DATABASE_PATH=str(folder / "store.sqlite3"),
            SHOP_PAYPAL_CLIENT_ID=client,
            SHOP_PAYPAL_CLIENT_SECRET=secret,
            SHOP_PAYPAL_MERCHANT_ID=seller,
            RESOLVE_API_URL=api,
            RESOLVE_API_KEY=issued.api_key,
        )
        child = subprocess.Popen(
            [node, "src/server.mjs"],
            cwd=SHOP,
            env=env,
            stdout=subprocess.PIPE if smoke else None,
            text=True,
            encoding="utf-8",
        )
        if smoke:
            first = child.stdout.readline().strip()
            prefix = "Field Brew Supply: "
            if not first.startswith(prefix):
                raise RuntimeError("The shop did not start.")
            checkout_smoke(first.removeprefix(prefix))
        elif child.wait() != 0:
            raise RuntimeError("The shop exited before checkout.")
    finally:
        if child and child.poll() is None:
            child.terminate()
            child.wait(timeout=10)
        if child and child.stdout:
            child.stdout.close()
        server.should_exit = True
        if thread:
            thread.join(timeout=10)
        listener.close()
        store.revoke_key(issued.key_id)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=4173)
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Create one real Sandbox order without approving or capturing it.",
    )
    args = parser.parse_args()
    location = (
        TemporaryDirectory(prefix="field-brew-sandbox-")
        if args.smoke
        else nullcontext(SHOP / "data" / "sandbox")
    )
    try:
        with location as folder:
            serve(Path(folder), 0 if args.smoke else args.port, args.smoke)
    except KeyboardInterrupt:
        return 0
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
