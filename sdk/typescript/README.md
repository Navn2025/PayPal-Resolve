# Resolve Evidence SDK for Node.js

Private investigations: `getInvestigations(caseId)` returns queued/running state
and completed or blocked results. `reviewInvestigation(caseId,id,{expected_revision,
evidence_snapshot,decision})` records `approve`, `reject` or `request_evidence`.
The receipt always has `authorizes_payment: false`; stale snapshots return 409.
These methods require a **full merchant key and direct FastAPI URL**. Scoped
commerce keys and the `/api/sdk` gateway do not expose investigation review.
See [automatic investigations](../../docs/AI_INVESTIGATIONS.md).

`@resolve-paypal/sdk` calls the Resolve API from your server. It lets a support
agent see what happened, what evidence supports it, and what is still missing.
It can also issue a private status link for the buyer. It needs a running Resolve
API and the appropriate merchant key for the workflow. Node.js 22.12+ and
TypeScript types are supported. The package has no runtime dependencies.

## Integrate with your IDE assistant

Copy the [resolve-sdk-integration skill](skills/resolve-sdk-integration/SKILL.md)
into your app's skill folder, keeping it at `resolve-sdk-integration/SKILL.md`,
or attach the file to your IDE chat. Give the IDE the path to the SDK preview
archive if the SDK is not installed in your app yet. Then paste:

```text
Use the resolve-sdk-integration skill to connect this app to my Resolve workspace.
Find where the server saves orders or payment updates and add the smallest
server-side sync so orders appear in Workspace → Orders. Reuse my existing
checkout and keep the SDK key in the server environment. Show me which settings
to add and how to verify one test order.
```

Copy the real settings from **Workspace → Settings → SDK keys** to your server
environment outside the IDE chat.

## Install this preview

The package is not published to npm. From the Resolve checkout:

```powershell
cd sdk/typescript
npm ci
npm pack
```

In your own application's backend, install the resulting
`resolve-paypal-sdk-0.5.0.tgz`:

```powershell
npm install path/to/resolve-paypal-sdk-0.5.0.tgz
```

## Quick start from the merchant dashboard

Sign in with your Resolve access key, then open **Settings → SDK keys**.
Select **Generate SDK key**, then **Copy SDK setup**. Paste the configuration
into your app server's environment. It includes the SDK gateway URL and the
new key; keep it out of browser code and Git.

From your server (for a standalone Node script, load the file with `node --env-file=.env your-script.mjs`):

```ts
import { createResolve } from "@resolve-paypal/sdk";

await createResolve().syncOrder({ id: "ORDER-123", status: "paid" });
```

That registers revision 1 in **Workspace → Orders**. For updates, pass the
order's next version, for example `version: 2`. Keep the same order ID and
app source. `payment` and `items` are optional; include them if you need PayPal
comparison or line items. For more than one app, give each a stable
`RESOLVE_APP_SOURCE`. The copied key only works for commerce actions. To
replace it, generate a new key, update your app, then revoke the old one.

If you already have a PostgreSQL reader pool, use
`createResolve().connectPostgres(pool).register(orderId)` or
`.registerAll()` for an initial import. The full [integration guide](../../docs/COMMERCE_INTEGRATION.md)
shows the database views and how to resume a backfill.

## Connect an app that already accepts PayPal

For the full setup, use the [commerce integration guide](../../docs/COMMERCE_INTEGRATION.md).
With the read-only [PostgreSQL views](examples/postgres-views.sql) and a dedicated
commerce API key, the SDK can sync one order and check PayPal in one call:

```ts
const evidence = resolve.connectPostgres(readOnlyPool, { source: "my-store" });
const report = await evidence.inspect("STORE-2042");
```

Use `syncCommerceOrder()` directly for other databases or ORMs,
`getCommerceOrder()` to read the latest comparison without calling PayPal,
and `refreshCommerceOrder()` to check again. Contacts are opt-in and full
merchant access is required to read them via `getCommerceContact()`.
The commerce key cannot call the general case or buyer-link methods below;
those retain their existing full merchant credentials.

[Run the PostgreSQL example](examples/connect-postgres.mjs) after installing
`pg` in your app. The SDK itself has no runtime dependencies.

To show routine orders in the dashboard, use `registerCommerceOrder(snapshot)`,
`evidence.register(orderReference)`, or the paginated `evidence.registerAll()`
backfill. These methods do not create a case for an order that doesn't have
one. The full [order dashboard workflow](../../docs/COMMERCE_INTEGRATION.md#show-all-orders-in-the-merchant-dashboard)
includes a resumable example and the endpoint contract.

## Add Resolve to your backend

Keep these values in your application's server environment:

```dotenv
RESOLVE_API_URL=http://127.0.0.1:8000
RESOLVE_API_KEY=your_resolve_merchant_access_key
```

`RESOLVE_API_URL` is the FastAPI base URL. Use HTTPS for a hosted API. Issue a
merchant key from the Resolve checkout with
`uv --directory backend run python -m app.manage issue-key --merchant-id YOUR_MERCHANT_UUID`.
Keep the key out of browser code and public environment variables. Verify
the connection with `await resolve.getMerchant()` after constructing the client.

For provider refreshes, use a Resolve backend with the
[PayPal Sandbox read settings](../../backend/README.md#paypal-sandbox-capture-reads)
configured for that merchant. The SDK itself does not receive PayPal
credentials or require the refund write flags.

```ts
import { ResolveClient } from "@resolve-paypal/sdk";

const resolve = new ResolveClient({
  baseUrl: process.env.RESOLVE_API_URL!,
  apiKey: process.env.RESOLVE_API_KEY!,
});

export async function inspectRefund(orderReference: string, captureId: string) {
  // Check that the caller can act on this order in your app first.
  const supportCase = await resolve.upsertCase({
    external_reference: orderReference,
    order_reference: orderReference,
    title: "Refund inquiry",
  });
  await resolve.linkRecord(supportCase.id, { kind: "paypal_capture", reference: captureId });
  await resolve.refreshEvidence(supportCase.id);
  return resolve.getEvidenceBundle(supportCase.id);
}
```

Run [examples/order-1042.mjs](examples/order-1042.mjs) after setting
`RESOLVE_API_URL`, `RESOLVE_API_KEY`, and `PAYPAL_CAPTURE_ID` in your server
environment. `PAYPAL_ORDER_ID` is optional. Run
`node node_modules/@resolve-paypal/sdk/examples/order-1042.mjs` from the
consumer app, or `node examples/order-1042.mjs` after building in this
checkout. The example records a USD 25 approval as merchant evidence and
shows which PayPal facts are available. It does not issue a refund.

| Method | What it does |
| --- | --- |
| `upsertCase(input)` | Uses a stable external reference per merchant. Save the returned `id`. Reusing the reference with different case data returns 409. |
| `linkRecord(id, input)` | Associates a PayPal order, capture, or refund ID, an internal order, or a support ticket. A link alone proves no provider outcome. |
| `addEvidence(id, input)` | Records an approval, return confirmation, or private note with a source, event ID, and event time. It is merchant-reported evidence. |
| `refreshEvidence(id)` | Reads PayPal Sandbox and returns newly checked facts, check time, and evidence issues. A failed check preserves earlier facts. |
| `getCase(id)` / `getEvidenceBundle(id)` | Reads the case, evidence summary, and last check. The bundle adds links and a page of evidence timeline events. |
| `getTimeline(id, options)` | Orders case events newest first by sequence. Pass `next_before_sequence` as `before_sequence` for the next page of `items`; legacy `refund_items` is a separate stream. Existing offset pagination still works. |
| `createBuyerLink(id)` | Uses the existing private link issuer. It replaces the previous link. |

Identical upserts, links, and evidence events return their existing records.
Keep event IDs stable per case and source. Changed input under the same key
returns 409; `ResolveApiError.code` distinguishes the conflict types. Use
decimal strings such as `"25.00"` for USD amounts.

PayPal Sandbox verification is scoped to the configured merchant and supports
one USD capture per case. If the capture response identifies its PayPal order,
Resolve tries to discover refunds from that order; otherwise link the PayPal
order ID explicitly. A known refund can be checked against its verified parent
capture even when order history is unavailable. Refund-only links without a
verified capture and non-PayPal references are reported as missing or unsupported.
The SDK distinguishes pending amounts, completed amounts, and partial refunds
without treating merchant approval as provider proof. A provider check cannot
move money or change a merchant approval.

Set `RESOLVE_CUSTOMER_PUBLIC_ORIGIN` or `RESOLVE_MERCHANT_WEB_ORIGIN` on
Resolve's backend so it can return `public_url`. Otherwise it returns the
one-time token with a null URL. Send the link only to the intended buyer;
anyone with the link can open its customer view until it expires or is revoked.
Issuing a new link replaces the old one, and `revokeCustomerLink(id)` disables
it. `getCustomerLink(id)` returns its status without disclosing the token.
The buyer sees safe status labels only; private notes, provider IDs and
merchant evidence remain in the merchant workspace.

`getMerchant()` checks access. `listCases({ limit, offset })` and
`getCaseTimeline(id, { limit, offset })` read merchant-only records.
`ResolveApiError.status` exposes HTTP failures; `ResolveTransportError.code`
distinguishes network, timeout, cancellation, and invalid responses. Requests
have a default 10-second timeout and can take an optional `AbortSignal`.
The SDK doesn't retry requests. If a create or link request times out, check
whether it succeeded before repeating it.

Other languages can call the same FastAPI REST endpoints
using the repository's [OpenAPI contract](../../postman/contracts/resolve.openapi.json).

## Develop and verify

Sync the Resolve backend with `uv --directory backend sync` from the repo
root. Run `npm test` here to generate TypeScript types from the checked-in
OpenAPI contract and exercise the SDK against real FastAPI with disposable
SQLite and synthetic keys. No configured database or PayPal account is used.
From the repo root, run the ORDER-1042 acceptance test through Postman:

```powershell
$env:RESOLVE_RUN_SDK_EVIDENCE_SIMULATION = '1'
try {
  postman simulation run postman/simulations/paypal-read/paypal-read.sim.yaml --proxy --lift 'npm --prefix sdk/typescript test' --output ndjson
} finally {
  Remove-Item Env:RESOLVE_RUN_SDK_EVIDENCE_SIMULATION -ErrorAction SilentlyContinue
}
```
