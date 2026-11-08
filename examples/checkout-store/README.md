# Field Brew Supply

A small coffee gear shop with six products. It creates PayPal Sandbox orders,
captures an approved payment, and sends the store order and items to Resolve
through the same Evidence SDK used by an external merchant app. Nothing ships.

## Start with your existing Sandbox app

From the Resolve repository root (Node.js 24 and uv required):

```powershell
uv --directory backend sync
npm --prefix sdk/typescript ci
npm --prefix sdk/typescript run build
npm --prefix examples/checkout-store ci
uv --directory backend run python ../examples/checkout-store/scripts/local_sandbox.py
```

Open [http://127.0.0.1:4173](http://127.0.0.1:4173). The launcher reads only
the Sandbox REST app client ID, client secret, and seller merchant ID from
`backend/.env` or the corresponding environment variables. It runs a separate
Resolve API and a demo merchant in `data/sandbox/`, with Sandbox refund writes
disabled and a temporary commerce key. It does not use the database configured
for the main Resolve app or print any credentials.

1. Add a product to your cart and select **Continue to PayPal Sandbox**.
2. Sign in to PayPal with a **Personal Sandbox buyer**, then approve the test
   purchase. You must approve as the buyer before the store captures.
3. Back in the store, the receipt shows payment status, a Resolve case ID, and
   the result of comparing the store's records with PayPal.
4. Select **Check again** to refresh the same Resolve case. If a partial refund
   is later recorded outside the store and is visible to the configured Sandbox
   app, the receipt reports the difference. Rechecking cannot charge or refund.

If checkout succeeds but Resolve is unavailable, the payment stays recorded in
the shop. **Check again** retries the SDK sync without submitting the payment
again. A pending capture can be checked again without a second capture request.

## Connect it to a different Resolve workspace

In this directory, copy `.env.example` to the ignored `.env`. Fill the three
`SHOP_PAYPAL_` values and set `RESOLVE_API_URL` to your running FastAPI origin.
Issue a [commerce key](../../docs/COMMERCE_INTEGRATION.md#start-here) for the
merchant whose PayPal Sandbox read connection uses the same seller and app.
Set that key as `RESOLVE_API_KEY`. Run `npm start` here.

This mode saves the shop's orders in `data/store.sqlite3` by default. With no
credentials, `npm start` serves the catalog and cart preview with checkout
disabled. The API binds only to loopback. Use the printed `127.0.0.1` origin,
including its port, for the PayPal return flow.

## What the demo sends to Resolve

The store calculates totals from its catalog, saves a separate SQLite order,
and calls `syncCommerceOrder()` followed by `refreshCommerceOrder()` only
after matching a completed capture to the stored order, seller and amount.
It sends the app order ID, product lines, currency, PayPal order and capture
IDs, the captured amount, and the store's recorded refund total. It never
sends buyer login information, a PayPal token, or raw payer details.

The browser starts checkout and displays results; the server holds credentials,
validates the approval and capture, and calls the SDK. Receipts are limited to
the browser session that created the order. Retries use the saved checkout
and capture request IDs and read the provider order before submitting a
capture. The demo is Sandbox only.

| Store route | Purpose |
| --- | --- |
| `GET /api/catalog` | Six products and whether checkout is configured. |
| `POST /api/orders` | Quote server-side and create or reuse the Sandbox order from `requestId` and product IDs/quantities. |
| `GET /api/orders/{id}` | Read the current receipt for the owning browser session. |
| `POST /api/orders/{id}/capture` | Check the returned PayPal `token` and capture only after provider approval, or recover a previous capture. |
| `POST /api/orders/{id}/verify` | Sync/refresh Resolve evidence for a completed payment without making another capture. |

The store follows the PayPal [Create order](https://developer.paypal.com/api/orders/v2/orders-create),
[Capture payment for order](https://developer.paypal.com/api/orders/v2/orders-capture),
and [Show order details](https://developer.paypal.com/api/orders/v2/orders-get)
contracts. PayPal Sandbox buyers and sellers use separate logins; see the
[existing purchase walkthrough](../../docs/SANDBOX_TEST_PURCHASE.md).

## Verify without a real buyer

Install the Chromium build required by the checkout example once:

```powershell
npm --prefix examples/checkout-store exec -- playwright install chromium
npm --prefix examples/checkout-store test
```

If Edge is already installed, you can set `$env:SHOP_TEST_BROWSER_CHANNEL = 'msedge'`
for the test instead of downloading a Chromium build.

The default test checks the mobile catalog and cart. For the automated checkout
test, run from the repo root:

```powershell
$env:RESOLVE_RUN_CHECKOUT_STORE_SIMULATION = '1'
$env:NODE_USE_ENV_PROXY = '1'
$env:NO_PROXY = '127.0.0.1,localhost'
try {
  postman simulation run postman/simulations/paypal-read/paypal-read.sim.yaml --proxy --lift 'npm --prefix examples/checkout-store test' --output ndjson
} finally {
  Remove-Item Env:RESOLVE_RUN_CHECKOUT_STORE_SIMULATION,Env:NODE_USE_ENV_PROXY,Env:NO_PROXY -ErrorAction SilentlyContinue
}
```

The checkout test uses Chromium, a real store process, the actual Resolve SDK
and API, isolated SQLite databases, and a simulated PayPal approval and capture.
It checks that a repeated request produces one capture and the same case,
then seeds a simulated external USD 5.00 refund and checks the discrepancy.
For an account-backed checkout setup check, pass `--smoke` to the launcher. It
creates an unapproved Sandbox order and exits without capturing it.
