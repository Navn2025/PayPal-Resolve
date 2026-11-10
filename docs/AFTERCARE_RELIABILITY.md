# Aftercare reliability and resolution assurance

CHG-050 implementation contract, 2026-11-10. Extend SDK order support into the
nine researched problems using the existing case and payment engines.

| Problem | Concrete addition |
|---|---|
| Return costs / abuse | Versioned merchant return policy, eligibility and quantity checks, disclosed fees, evidence/inspection review flags. Flags require review; they do not declare fraud. |
| Dispute evidence | Reason-specific evidence requirements and provenance in reviewed packages. |
| Refund / dispute overlap | Versioned dispute records with stable event IDs and capture-wide holds checked by approval, execution and recovery. |
| Missing refund | Provider-supported refund journey plus separately labelled merchant trace references and buyer receipt acknowledgement. No claim that processor completion proves bank receipt. |
| Repeated explanations | One order context with issues, public promises, conversation and next actions, shared with the owned merchant case. |
| Return instructions / labels | Merchant return guide and authenticated PDF label download/save in the buyer portal and SDK. Label purchase remains external. |
| Duplicate / out-of-order events | Monotonic order revisions and durable PostgreSQL SDK projection consumer with transaction-bound deduplication. |
| Missed events | Resumable state-change feed, explicit reconciliation and bounded periodic scan. Consumers can recover current state without relying solely on webhooks. |
| Ambiguous timeout | Stable-payload retries only on idempotent SDK actions, issue receipt lookup, bounded retry/time budgets; no automatic retry of link rotation or financial actions. |

Storage is additive: SQLite 028 / PostgreSQL 019. Keep all earlier numbered
migrations unchanged. Source-specific support grants apply to the new customer
SDK methods. Staff roles and ownership checks still apply to merchant actions.

The event feed reports reconciled safe state snapshots, not a promise to deliver
every intermediate transition. Domain history remains in the existing audit
tables. PostgreSQL consumer callbacks should update app rows or an app outbox in
the supplied transaction; external side effects still need their own idempotency.

Dispute ingestion may accept merchant-recorded provider references, but labels
them as merchant recorded. No new Stripe account integration or live bank-credit
observation is implied. Existing authenticated PayPal reads and webhook handling
remain provider-specific. Physical return receipt and inspection are distinct
from carrier delivery. Real eligibility must also respect applicable merchant
obligations; policy configuration is not legal advice or an automatic legal ruling.

Validate synthetic migrations/import, amount precision/shared captures,
pending/failed refunds and all payment gates; return policy/revision/label privacy;
duplicate and stale dispute events; resumable snapshots; SDK retry ambiguity and
PostgreSQL transaction rollback/concurrency; real merchant/buyer mobile paths.
Regenerate FastAPI OpenAPI/SDK types and update the engineering log with actual
checks and activation limits before handoff. No live money or notifications are
part of implementation verification.

## Using the workflows

Open **Operations → Connections → Return policy and review checks**. An owner
can enable a return window, disclose a restocking fee and shipping payer, request
item evidence, exclude products from automatic eligibility and require inspection.
Unknown or out-of-window dates and repeated requests create review flags, not a
fraud verdict. Buyers can still request review. Quantity limits remain hard gates
and cannot be overridden by a policy exception. No fee is charged automatically.
Policy changes and stale inspections require a current review; an owner/manager
can record a documented exception. Inspections remain merchant-recorded findings.

In a case, open **Guided returns and replacements → Return instructions, saved
labels and inspection**. Save the address/instructions and upload an existing PDF
return label (maximum 2 MiB). The buyer can download/save it from the private portal
and print later. The carrier label must already have been purchased or arranged;
Resolve neither purchases postage nor promises a carrier pickup. Item evidence is
uploaded through the existing private buyer evidence flow. A clear inspection
must refer to the current return and policy revision before its milestone advances.

Open **Dispute safety, refund tracing and evidence requirements** in the case.
After linking a payment, managers/finance/owners can record stable, versioned
dispute updates. Active or reimbursed disputes hold the shared capture across
all its cases. Older events are recorded as ignored; conflicting identities or
versions fail. A reimbursement cannot be erased by changing a later status to
“no refund.” Known PayPal dispute-handoff promises also hold the capture until
reviewed. Existing verified PayPal dispute reads remain available through that
promise; Stripe/bank references here are merchant-recorded, not live connectors.
These holds block new approvals, execution claims and uncertain recovery POSTs.
Read-only reconciliation remains possible. A hold cannot recall a payment POST
already sent before the hold was recorded.

Finance/owners can add an ARN/STAN/RRN/bank reference obtained from their provider
for a refund recorded against this capture. Buyers see a labelled merchant trace
reference alongside provider evidence. Provider completion is described as sent
to the original payment method, not verified receipt in a bank. Unverified/stale
amounts stay null. Buyer acknowledgement is explicitly buyer-reported and changes
no payment ledger or approval. Trace data is not automatically retrieved from a
bank; availability of a valid reference depends on the payment provider.

Classify original delivery, product description, policy, authorization,
cancellation or credit evidence using notes and owned customer attachments.
Packages now use the selected dispute reason to list evidence requirements and
include labelled documents, return checks and label hashes. Replacement delivery
is not silently treated as original delivery. A checklist entry being present
establishes only that recorded support is available; it does not verify document
authenticity, win a dispute or submit anything to PayPal. Changed sources make
older packages stale for review/export.

## SDK customer methods

These use the existing explicit support key and source. The merchant app must
still check that its authenticated customer owns the requested order.

```ts
const context = await resolve.getSupportContext(orderId);
const journey = await resolve.getRefundJourney(orderId);
const eligibility = await resolve.getReturnEligibility(orderId, {
  items: [{ product_id: "CUP", quantity: 1 }],
  deliveredAt: trustedDeliveryTimestamp,
});
const returned = await resolve.requestOrderReturn(orderId, {
  requestId: savedReturnRequestId,
  items: [{ product_id: "CUP", quantity: 1 }], reason: "Damaged item",
});
const guide = await resolve.getReturnGuide(orderId, returned.id);
const label = await resolve.downloadReturnLabel(orderId, returned.id, guide.labels[0].id);
```

`getOrderReturns` returns owned item/quantity progress. `lookupIssue(orderId,
requestId)` recovers an already-committed receipt after a lost response.
`acknowledgeRefundReceived` records the authenticated customer's acknowledgement,
not a bank observation. The context includes original requests and a page of the
same public case conversation, with an older-message cursor. Imported private
support notes and private merchant financial notes stay excluded.

Merchant SDK helpers (`saveReturnPolicy`, `saveReturnGuide`, `uploadReturnLabel`,
`recordReturnInspection`, `recordDispute`, `recordRefundTrace`,
`recordDisputeEvidence`) require a full merchant key and direct FastAPI URL.
Never give these credentials to the buyer or bundle them into browser code.

## Reliable synchronization and retries

`pullEvents({ afterSequence, limit })` is a resumable, authenticated state-change
feed scoped to the merchant/app source. It reconciles up to 100 least-recently
checked owned cases per call; ongoing calls and the separate operations worker
cover larger workspaces fairly. Store the returned cursor after processing. The
feed includes safe resolution/return state, public conversation version, label/
policy changes and refund journey. It excludes private notes and label bytes.

Run `uv run python -m app.operations_worker --loop` to also reconcile connected
app state periodically. This worker sends no customer messages or financial POSTs.
The feed can recover missed current state without an inbound webhook; it is not
an outbound webhook subscription and does not guarantee every transient state.
Domain audit/history retains the original business records.

For a Node app with a writable integration PostgreSQL database:

```ts
import { PostgresResolutionConsumer } from "@resolve-paypal/sdk";
const first = await resolve.pullEvents();
const consumer = new PostgresResolutionConsumer(pool, {
  merchantId: first.merchant_id, source: first.source, consumerId: "order-page",
});
await consumer.initialize(); // Explicitly creates two SDK tables in this database.
await consumer.poll(resolve, async (event, transaction) => {
  await transaction.query(
    "UPDATE my_orders SET support_state=$1 WHERE id=$2",
    [event.snapshot.resolution.stage, event.order_reference],
  );
});
```

Use a stable consumer ID. The consumer serializes concurrent passes, ignores
processed events and older order revisions, rejects scope/revision conflicts,
and commits app writes, its projection and cursor together. A callback failure
rolls them all back. Callbacks must use the supplied transaction; enqueue external
notifications in the app's own outbox there. Direct external effects still need
independent idempotency and cannot be made exactly-once by this SQL transaction.
The SDK has no `pg` runtime dependency; the host app supplies its existing pool.

SDK retry-safe actions get at most three attempts by default (`retryAttempts`
1–4), preserving the serialized payload and request ID within the overall timeout.
Network errors and short 429/5xx responses are retried; authentication, validation,
conflict, long rate limits and cancellation return to the caller. Portal-link
rotation and merchant mutations are not automatically retried. On an exhausted
request deadline, use the same durable request ID or `lookupIssue`; never invent
another ID to resolve an unknown outcome. No SDK retry executes a refund.

## Verification and activation

All development uses disposable databases and synthetic accounts. The engineering
log records actual checks, provider simulation boundaries, schema versions and
browser results. New migrations are SQLite 028/PostgreSQL 019, and SDK 0.7 remains
a local preview archive. No live bank account, new payment connector, postage
purchase, customer notification, hosted deployment or dispute submission is
implicitly configured by installing the SDK.

Active return policies disclose the delivery window, shipping payer, restocking
fee and evidence/inspection requirements before a buyer submits a request. The
capability-protected public view omits the merchant's excluded-product catalog.
An inactive policy returns a null fee and asks the merchant to confirm costs;
it does not advertise free returns. Eligibility remains advisory until approval.
