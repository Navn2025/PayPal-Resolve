---
name: resolve-sdk-integration
description: Integrate the Resolve Evidence SDK into a merchant's Node.js app. Use when wiring Resolve SDK keys, syncing app orders to the merchant dashboard, importing existing orders, or comparing an app's PayPal payment records with Resolve evidence.
---

# Integrate the Resolve SDK

## Connect the app

1. Inspect the target app's package manager, server runtime, order model, and trusted code path that persists order or payment changes. Reuse its checkout, database access, and retry mechanism. Resolve's SDK needs Node.js 22.12+ and runs only on the server.
2. Reuse `@resolve-paypal/sdk` if it already supports `createResolve().syncOrder()`. Otherwise, install the supplied SDK preview archive in the app's server package using its package manager, for example `npm install path/to/resolve-paypal-sdk-0.5.0.tgz`. This preview is not published to npm. If the Resolve source is available and the archive is missing, run `npm ci` then `npm pack` in its `sdk/typescript` directory. If neither is available, identify the missing archive instead of substituting another package.
3. Have the merchant sign in with their Resolve access key and open **Workspace → Settings → SDK keys → Generate SDK key → Copy SDK setup**. Use the generated commerce key in the app's server environment. Add placeholders to an existing environment example if needed:

   ```dotenv
   RESOLVE_API_URL=https://YOUR-RESOLVE-HOST/api/sdk
   RESOLVE_API_KEY=
   RESOLVE_APP_SOURCE=my-store
   ```

   Use the copied gateway URL, with HTTPS when hosted or HTTP on loopback for local development. Use a stable, distinct source per app; do not change it when rotating the key. The key is shown once. Keep the real key in local or hosted server secrets, out of prompts, Git, logs, and public browser environment variables.

## Sync an order

The minimal server-side call for a new order is:

```ts
import { createResolve } from "@resolve-paypal/sdk";

await createResolve().syncOrder({ id: "ORDER-1042", status: "paid" });
```

Replace the sample values with the app's persisted order ID and status. Use a server path that runs after the app saves the order or confirms and saves the payment. Never infer payment success from a browser redirect. Use the app's existing job or error handling so a Resolve sync failure does not undo a saved order or successful payment.

- `syncOrder` publishes an order in **Workspace → Orders** without creating a support case. It defaults to version 1. To sync updates, pass the app's durable, increasing integer revision as `version`, retaining the same source and ID. If the app has no durable revision, use the create-only path for the first integration or add a revision as part of the same app transaction when updates are requested.
- Build an explicit allowlist from the current persisted state. Each update is a snapshot, so include prior linked PayPal IDs and all fields the integration still shares. Retry a transient failure with the same version and payload. A `409` with `commerce_conflict` means the snapshot is stale or conflicts with existing data; inspect the authoritative state before sending another version.
- Never send raw rows, raw PayPal payloads, passwords, payment card data, or secrets. Contact name, email, or phone are optional; share them only when the merchant has asked to share them and they serve the workflow. Leave them out of routine examples and logs.

## Add PayPal comparison or import orders when requested

- For comparison, add a `payment` object from the app's trusted payment record: `paypal_order_id`, `paypal_capture_id`, `currency: "USD"`, and any known `status`, `captured_amount`, or `refunded_amount`. This SDK workflow supports one USD capture per order. Use decimal strings for amounts, count completed refunds only in `refunded_amount`, and omit unknown values. Payment status accepts `pending`, `completed`, `partially_refunded`, `refunded`, or `failed`. If sharing line items, map each to `{ product_id, quantity }` plus optional `name`, `sku`, or `unit_amount` (at most 50).
- The synced data is app-reported. For a specific order, open or reuse its case from **Workspace → Orders**, then check the comparison with the workspace's configured PayPal Sandbox connection. A server integration with the case ID can call `refreshCommerceOrder(caseId)` and read the result with `getCommerceOrder(caseId)`. Report missing or unverified evidence as such. The SDK key does not enable general case actions, reading the merchant's catalog or contacts, or moving money.
- For an initial import, page through existing orders on the app server and call `syncOrder` with the same source, stable IDs, and versions as ongoing sync. Preserve a checkpoint so an interrupted import can resume. If the app already uses Resolve's `resolve_evidence` PostgreSQL views and a read-only pool, use `createResolve().connectPostgres(pool).register(orderId)` or iterate `.registerAll({ after, pageSize })` instead. The SDK does not automatically discover app tables, grant database access, or import PayPal history. Only run a live backfill when the merchant requests it.

## Verify the integration

Run the app's relevant checks. With a local or authorized test workspace, sync one synthetic order, repeat the exact request, and verify it appears once under the expected source in **Workspace → Orders**. If wiring updates, change the order in the app and check that the same row advances to the next version. If testing PayPal comparison, use Sandbox evidence and distinguish a saved app order from a verified provider result. If the package, connection, or workspace is unavailable, say what was verified locally and what remains for the developer to test.
