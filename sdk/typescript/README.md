# Resolve Evidence SDK for Node.js

`@resolve-paypal/sdk` calls the Resolve API from your server. It lets a support
agent see what happened, what evidence supports it, and what is still missing.
It can also issue a private status link for the buyer.
It needs an existing Resolve API and merchant access key. Node.js 22.12+
and TypeScript types are supported. The package has no runtime dependencies.

## Install this preview

The package is not published to npm. From the Resolve checkout:

```powershell
cd sdk/typescript
npm ci
npm pack
```

In your own application's backend, install the resulting
`resolve-paypal-sdk-0.2.0.tgz`:

```powershell
npm install path/to/resolve-paypal-sdk-0.2.0.tgz
```

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
