# Embedded order aftercare

Implemented for CHG-049, 2026-11-10: give the SDK a complete customer-support
workflow inside a merchant's existing order page. The server authenticates its
customer and verifies order ownership before calling Resolve. A dedicated support
key explicitly grants this workflow for one app source; existing commerce-only
keys retain their restrictions. No app-supplied complaint becomes an approved
merchant promise or authorizes a refund.

## Workflow contract

1. Existing `syncOrder` publishes the order from trusted server data.
2. `openIssue({orderId,requestId,reason,message,requestedResolution})` atomically
   opens/reuses the order's case and records one customer issue/message. Retries
   reuse the same request ID; changed requests conflict. No duplicate case/message.
3. `getOrderResolution(orderId)` returns a customer-safe progress summary, current
   promised remedies, overdue flag, refund verification/freshness and next action.
   It returns `no_issue` for a known order with no case, without creating one.
   Unknown orders are 404; private merchant evidence/notes are never returned.
4. `createSupportLink(orderId)` explicitly issues an expiring buyer capability
   link for that existing case. It replaces the prior case link, like the current
   merchant issuer. Buyers can then use offers, messages, uploads and returns in
   the existing portal. Session creation is an explicit action, not status polling.

API: POST `/aftercare/issues`, `/aftercare/status`, `/aftercare/portal`, JSON order
locator `{source,order_reference}`. All are bounded, private/no-store and available
through the server-authenticated `/api/sdk` gateway. Status is a read-only POST to
keep private order references out of URLs. No provider refresh occurs while
polling. The merchant can refresh existing provider evidence separately.

Storage: new immutable SQLite 027 / PostgreSQL 018 migrations add explicit
per-key support grants and idempotent issue receipts. Existing schemas and old
commerce permissions remain intact. Owner-created support keys are still unable
to access general merchant operations, financial execution or team management.

The SDK/server tests and simulated store browser flow cover the actual use case,
with disposable data. The store simulation passed with 19 mocked provider requests
and zero pass-through. CHG-049 in the engineering log records final commands,
counts, migration/import validation and remaining limits.

## Merchant setup

Open **Operations → Connections → Customer support inside your store**. Choose
the same source your app uses when syncing orders, generate a support integration
key, and copy the server settings. Old order-only keys deliberately remain
order-only. The support grant is source-specific; the underlying key retains the
existing commerce permissions. Revoke it using the same key list. Already issued
buyer links have their own expiry/revocation; revoking a server key stops further
API requests but does not revoke an existing buyer capability.

Install the local SDK 0.6 preview archive or use the repository's linked package.
The package is not published to npm. Keep integration code in the app's backend,
never bundle the key into a storefront. This feature needs no new environment
secrets or worker. Existing workers and optional provider connections still
perform their existing tasks. `getOrderResolution` reads cached evidence and makes
no external request; it is safe to use when opening an authenticated order page.

## What the customer sees

| Status field | How to use it |
|---|---|
| `stage: no_issue` | A known order has no case; offer “Report a problem.” Reading status creates nothing. |
| `stage: under_review` | The case is with the merchant. Show `next_step.action` and any due date. |
| `next_action: review_offer` | A current offer awaits the buyer. Show “Review offer,” then create/open a portal link. |
| `next_action: open_portal` | The merchant needs a customer update. Show the messages/returns entry point. |
| `stage: pending` | The recorded resolution is awaiting its next result. Display the supplied next step. |
| `stage: needs_review` | Evidence needs review; avoid promising an outcome. |
| `stage: resolved` | Current promised remedies are fulfilled according to their evidence sources. |
| `promises[].provider_confirmed` | Distinguishes provider-confirmed completion from merchant-recorded completion. |
| `refund.verification: current` | Complete provider history is fresh (at most five minutes) and the owning connection has not changed. Completed and pending amounts are separate. |
| `refund.verification: unverified` | Completed/pending/remaining amounts are null. Show that a check is needed, not “no refund.” |

All results have `authorizes_payment: false`. Customer requests are not promises;
merchant review and existing approval/condition/acceptance gates remain separate.
No app endpoint executes a refund or replacement. Status contains public promise
terms, not private notes, payment identifiers, raw sources or conversations.
Portal sessions deliberately expose the customer's existing case conversation,
attachments, offers and return controls, just like ordinary private buyer links.

## Runnable use case

The [Field Brew store](../examples/checkout-store/README.md) now shows a
**Need help with this order?** section on a paid, synced receipt. Its own HttpOnly
browser session scopes every support action to the owned order. The server calls
`openIssue`, `getOrderResolution` and `createSupportLink`; the browser never sees
the SDK key. It persists a request UUID for identical retries. The production app
integrating Resolve should use its own account/order authorization and durable
retry storage in the same way.

The sample covers damaged/not-received/wrong-item/refund-not-received reports,
requested refunds/replacements/returns/advice, status refresh, and portal entry.
It coordinates the current merchant workflow; actual physical fulfillment remains
merchant-arranged and provider verification is presently PayPal Sandbox only.

Merchant case details also show **Customer requests from connected apps** with
the reported problem, requested remedy, app source and date. This is separate
from the merchant's promises and approvals. The private merchant projection is
`GET /platform/cases/{case_id}/support-requests`; support keys cannot read it.
