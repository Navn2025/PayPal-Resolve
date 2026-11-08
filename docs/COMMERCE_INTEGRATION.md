# Connect a merchant app to Resolve

Use this integration when your application already accepts PayPal and you want
support staff to see the app's order and PayPal's evidence in the same Resolve
case. Start by sharing one selected order; the SDK does not scan or backfill
your entire database.

## Show all orders in the merchant dashboard

Sign in to your regular Resolve merchant workspace and select **Orders**.
The dashboard lists the orders your apps have registered for that merchant,
including unpaid orders and orders without a support case. Search by store
order reference or PayPal order/capture ID, or filter by source. Select an order
to see the app snapshot. Use **Create resolution case** only when the order
needs investigation; it keeps the same order and opens the existing case
workspace with the evidence attached.

Point your app at the **same Resolve API and merchant** as the dashboard. Use
`registerCommerceOrder(snapshot)` for every order, then call it again after
changes to the order, payment, or line items. A revision is an integer that
increases when those fields change. Use one stable source name for both backfill
and ongoing events so historical and new snapshots update the same order.

For existing PostgreSQL orders, the adapter reads the authorized orders view
in batches. Start ongoing sync before backfill so concurrent app changes are
also sent. Save the checkpoint after each successful registration:

```ts
const orders = resolve.connectPostgres(readOnlyPool, { source: "my-store" });
for await (const receipt of orders.registerAll({ after: savedCheckpoint, pageSize: 50 })) {
  await saveCheckpoint(receipt.order_reference);
}
```

Run [the import example](../sdk/typescript/examples/import-orders.mjs) with the
same environment as the PostgreSQL example below and optionally set
`RESOLVE_APP_SOURCE` and `RESOLVE_IMPORT_AFTER`. If an order changes during
backfill, a stale revision can be rejected; read the latest row and retry, or
resume after a checkpoint only when that order has already been synced.
For other databases, page through your own orders and pass each snapshot to
`registerCommerceOrder` or `POST /commerce/orders/register`. Resolve doesn't
pull a merchant's PayPal history or connect to the app's database on its own.

The demo store's isolated launcher uses a separate merchant and database. It
does not populate the regular dashboard. To connect Field Brew to the regular
workspace, use its [external workspace setup](../examples/checkout-store/README.md#connect-it-to-a-different-resolve-workspace).
An existing Sandbox purchase can be registered with its original PayPal IDs
without approving or capturing a new payment.

## Start here

1. Sign in with your Resolve access key and open **Settings → SDK keys**.
   Select **Generate SDK key** and **Copy SDK setup**. Use a new access-key
   sign-in if Resolve asks you to reauthenticate. A generated key is displayed
   once. The same screen lists active key IDs and lets you revoke them.
2. Paste the copied `RESOLVE_API_URL`, `RESOLVE_API_KEY`, and optional
   `RESOLVE_APP_SOURCE` into your app server's environment. Use a different
   stable source per app. Never include the key in browser code.
3. Install the [Node.js SDK archive](../sdk/typescript/README.md#install-this-preview)
   or call the direct HTTP endpoints. An SDK key cannot sign in, read
   merchant contacts, open cases from the dashboard, or execute a payment.

```ts
import { createResolve } from "@resolve-paypal/sdk";

await createResolve().syncOrder({ id: "STORE-2042", status: "paid" });
```

This publishes revision 1 in **Orders**. Send the same ID with a higher
`version` when the order changes. This call doesn't need a PayPal connection;
add the app's payment fields and configure [PayPal Sandbox reads](../backend/README.md#paypal-sandbox-capture-reads)
if you want to verify the payment. Refund write flags are unnecessary.

The copied URL ends in `/api/sdk` on your Resolve web app. That gateway accepts
a bearer key and exposes commerce registration, case-first sync, and
evidence read/refresh only. For other backend operations, use your configured
FastAPI URL directly. Local administrators can still issue a commerce key
without the dashboard:

```powershell
uv --directory backend run python -m app.manage issue-key --merchant-id YOUR_MERCHANT_UUID --scope commerce
```

## Option 1: Read PostgreSQL from your Node server

Apply the [view and grant template](../sdk/typescript/examples/postgres-views.sql)
in your **application database** after mapping your tables. Use an app-owned
database login that inherits only the relevant view grants. The SDK receives
a pool, not your schema, password, or raw tables; the database connection stays
inside your Node server. Do not reuse an admin, application writer, or shared
role with broader grants.

| App evidence view | Required columns and mapping |
| --- | --- |
| `resolve_evidence.orders` | `order_reference` (text), `revision` (positive integer), `order_status` (text or null), `customer_reference` (opaque ID or null). One row for the chosen order. |
| `resolve_evidence.payments` | `order_reference`, `paypal_order_id`, `paypal_capture_id`, `currency`, normalized `status`, `captured_amount`, `refunded_amount`. Export at most one PayPal USD payment per order. An order can be synced before payment. |
| `resolve_evidence.items` | `order_reference`, stable sortable `line_id`, `product_id`, `name`, `sku`, `quantity`, `unit_amount`. Export the order's line quantity and historical price; name and SKU may be null. At most 50 items. |
| `resolve_evidence.contacts` | **Optional**: `order_reference` and the approved columns from `name`, `email`, and `phone`. [Optional view template](../sdk/typescript/examples/postgres-contact-view.sql). No contact view is queried by default. |

Use decimal amounts in USD, not integer cents, in the views. The SDK reads
money as text so amounts do not pass through JavaScript floating point. Use
payment statuses `pending`, `completed`, `partially_refunded`, `refunded`, or
`failed`. Use `null` for unknown amounts or status, and use `0.00` only when you
know the total is zero. `refunded_amount` means the sum of **completed** refunds.
Use a stable app revision and increment it in the same app transaction as any
change to the exported order, payment, items, or shared contact fields. If
changing which contact fields you share, increment the affected order's
revision before re-syncing. In a shared database, apply the correct merchant
row filter to every view; the SDK role must only be able to read that merchant's
data. The views use [PostgreSQL view permissions](https://www.postgresql.org/docs/18/sql-createview.html)
with explicit SELECT grants.

```ts
import { Pool } from "pg";
import { ResolveClient } from "@resolve-paypal/sdk";

const resolve = new ResolveClient({
  baseUrl: process.env.RESOLVE_API_URL!,
  apiKey: process.env.RESOLVE_API_KEY!,
  timeoutMs: 30_000,
});
const pool = new Pool({
  connectionString: process.env.APP_EVIDENCE_DATABASE_URL!,
  connectionTimeoutMillis: 5_000,
  statement_timeout: 5_000,
});
const evidence = resolve.connectPostgres(pool, { source: "my-store" });

// Check that the caller is authorized for this order in your app first.
const report = await evidence.inspect("STORE-2042");
```

Reuse the pool and client in your server. `evidence.inspect(orderId)` reads one
order, syncs it, and refreshes the linked PayPal evidence. Use
`evidence.sync(orderId)` for an update that makes no PayPal request. Either can
take `{ caseId }` to attach an existing owned Resolve case with the same order
reference (or no order reference). The pool only receives a
[parameterized query](https://node-postgres.com/features/queries#parameterized-query)
for that order. The app database and Resolve database do not need to be the
same engine or reachable from each other.

For an end-to-end starter, run [connect-postgres.mjs](../sdk/typescript/examples/connect-postgres.mjs)
with your read-only app database URL and order ID. Install `pg` in the app and
run from its project root:

```powershell
npm install pg
node node_modules/@resolve-paypal/sdk/examples/connect-postgres.mjs STORE-2042
```

## Option 2: Push a snapshot from any backend

Use `resolve.syncCommerceOrder(payload)` or call the API from your existing
server, for example after an order/payment changes or when a support case opens.

```json
{
  "source": "my-store",
  "order_reference": "STORE-2042",
  "revision": 1,
  "order_status": "shipped",
  "customer_reference": "CUSTOMER-42",
  "payment": {
    "paypal_order_id": "EXAMPLEPAYPALORDER",
    "paypal_capture_id": "EXAMPLEPAYPALCAPTURE",
    "currency": "USD",
    "status": "completed",
    "captured_amount": "100.00",
    "refunded_amount": "0.00"
  },
  "items": [{"product_id": "PRODUCT-42", "name": "Desk lamp", "quantity": 2, "unit_amount": "50.00"}]
}
```

```powershell
$headers = @{ Authorization = "Bearer $env:RESOLVE_API_KEY" }
$sync = Invoke-RestMethod -Method Post -Uri "$env:RESOLVE_API_URL/commerce/orders/sync" -Headers $headers -ContentType "application/json" -InFile "order.json"
Invoke-RestMethod -Method Post -Uri "$env:RESOLVE_API_URL/resolution-cases/$($sync.case_id)/commerce/refresh" -Headers $headers
```

| Endpoint | Purpose |
| --- | --- |
| `POST /commerce/orders/register` | Register or update an order using a commerce key. Returns its stable Resolve order ID and optional case ID. |
| `GET /commerce/orders` / `GET /commerce/orders/{order_id}` | Full merchant access: browse, search and read app snapshots without PayPal calls or shared contact fields. |
| `POST /commerce/orders/{order_id}/case` | Full merchant access: create or reuse the order's case and link evidence. |
| `POST /commerce/orders/sync` | Create or reuse a case by merchant, source and app order ID. Save the latest snapshot and link PayPal IDs in one transaction. Optional `case_id` attaches an existing owned case. |
| `GET /resolution-cases/{case_id}/commerce` | Read the current snapshot and comparison, without making a PayPal request. |
| `POST /resolution-cases/{case_id}/commerce/refresh` | Check linked PayPal Sandbox evidence and return the refreshed comparison. |
| `GET /resolution-cases/{case_id}/commerce/contact` | Read approved contact fields if present. Requires full merchant access. |
| `GET /resolution-cases/{case_id}/evidence-bundle` | Full merchant access: return the existing timeline and verified evidence plus the app comparison, without contact fields. |

Identical requests for the current revision reuse the receipt, including
concurrent requests. A changed payload at the same revision, a stale revision,
a conflicting case binding, or replacement/removal of an existing PayPal
reference returns `409`. A capture can be added later. Established payment IDs
stay attached to their case so a correction cannot silently rewrite the
identity of previously recorded evidence. Check IDs before the first sync.
The endpoint accepts at most 32 KiB and rejects unknown fields. See the
[OpenAPI contract](../postman/contracts/resolve.openapi.json) for types.

## What the comparison means

Resolve records the app's snapshot as merchant-reported evidence. It compares
PayPal order and capture identifiers, currency, gross captured amount, payment
status, and the completed refund total when it can reconcile the order.
It reports `match`, `mismatch`, or `incomplete`, with app and provider values
where known and a check time per verified field. `missing_app` means PayPal
confirmed a fact but the app did not supply it. `unverified` means Resolve lacks
applicable provider evidence. A newer app revision needs a check started after
its sync, even if an older check finished later. An outage leaves the earlier PayPal facts in the evidence bundle, but the current
comparison won't present those facts as freshly confirmed. Disagreement never
changes either the app's tables or PayPal.

The current provider scope is the configured seller's PayPal Sandbox, one USD
capture per order. Add the actual PayPal order ID if the capture does not
identify it. An unsupported or incomplete history is reported explicitly; it
cannot establish zero refunds. Product and customer details remain app records,
not independently verified PayPal facts. The integration does not onboard
arbitrary sellers or pull cross-app or live payment history.

## Contact and credentials

By default, only an opaque customer reference is read. To share contact data
intentionally, select just the approved fields in the PostgreSQL grant and
`contactFields: ["email"]` (or submit those fields in the direct API's `contact`
object). Resolve keeps only the latest contact data on that case. An updated
revision that omits `contact` removes it from the app-facing record. It is not
included in the comparison, evidence bundle, timeline, buyer view, or automatic
messages. It does not enroll a buyer in My cases. No password, password hash,
auth token, card data, or full user row belongs in the integration.
