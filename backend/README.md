# Resolve backend

FastAPI backend for recording customer cases, payment references, and refund
commitments. Cases, refunds, and condition checks persist in a local SQLite file.
Payment and refund details are submitted development data. An optional,
disabled-by-default client can read PayPal Sandbox capture details and retain a
scoped verification observation. Separate opt-ins enable approved Sandbox refunds
and repeated partial execution after order-scoped reconciliation. See the
[execution contract](../docs/REFUND_EXECUTION.md) and [workflow guide](../docs/PAYPAL_RECONCILIATION.md).

## Run locally

From the `backend` directory:

```powershell
uv sync
uv run uvicorn app.main:app --reload
```

Interactive API documentation: <http://127.0.0.1:8000/docs>.

## Merchant access

Create a local merchant and token from the backend directory:

```powershell
uv run python -m app.manage create-merchant --name "My development store"
```

The command prints a merchant ID, key ID, and `api_key` once. Save the token
privately; the database retains only its SHA-256 hash. It is a random access
token, not a password or PayPal credential. No public registration endpoint exists.

In `/docs`, select **Authorize** and paste only the token. Requests use
`Authorization: Bearer <api_key>`. `GET /auth/me` returns the authenticated merchant.
All case, refund, condition, and reconciliation endpoints require authentication;
`POST /health` stays public. Missing, invalid, or revoked credentials return `401`.
Another merchant's case returns `404`, just like a missing case.

Ownership comes from the token, never a request-body merchant ID. Capture and
refund identifiers are scoped to a merchant: the same sample ID in another
merchant's records neither exposes nor alters your balance. Shared capture
history applies only within the owning merchant.

Additional local administrator commands:

```powershell
uv run python -m app.manage issue-key --merchant-id <merchant_uuid>
uv run python -m app.manage revoke-key --key-id <key_uuid>
```

New keys do not revoke older keys automatically. Revocation blocks subsequent
requests using that key. Tokens currently have no automatic expiry. These commands
require trusted access to the database file; they are not exposed through HTTP.
Supabase Auth, browser login, user roles, and production identity remain future work.

### Existing anonymous development records

Schema migration 2 preserves existing records under an unassigned legacy merchant
with no access key. Creating a merchant does not automatically grant those records.
To explicitly assign all unassigned sample records to your development merchant:

```powershell
uv run python -m app.manage claim-legacy --merchant-id <merchant_uuid>
```

The assignment is atomic and refuses conflicting capture/refund IDs in the target
merchant. Existing case IDs and evidence notes are preserved. Run this only when
those old local records belong to that merchant. No automatic ownership inference
or PayPal-account ownership verification is performed.

## PayPal Sandbox capture reads

This integration is disabled by default and only targets
`https://api-m.sandbox.paypal.com`. It exchanges sandbox app credentials for an
OAuth access token and reads an existing capture; it cannot create payments or refunds.

### First-time setup

1. Sign in to the [PayPal Developer Dashboard](https://developer.paypal.com/dashboard/).
2. Under **Testing Tools > Sandbox Accounts**, use/create a business seller and
   a personal buyer. These are separate from live PayPal accounts.
3. Under **Apps & Credentials**, select **Sandbox**, create a Merchant app tied
   to that business account, and copy the client ID and client secret privately.
4. Use the sandbox seller's login at [sandbox.paypal.com](https://sandbox.paypal.com/signin/).
   Under the profile menu, open **Account Settings > Business information** and
   note **PayPal Merchant ID**. This is distinct from Resolve's UUID returned by
   `create-merchant` or `GET /auth/me`.
5. Copy the optional fields in `.env.example` to your ignored `backend/.env` and
   fill them locally. Never commit or paste the client secret into chat.
6. Restart the backend. Make a sandbox purchase using your app and sandbox buyer
   with the [official checkout sample](https://developer.paypal.com/checkout/integrate).
   Its captured order response contains `purchase_units[].payments.captures[].id`.
   Create a Resolve case using that actual **capture ID** and original amount.
   A PayPal order ID is not a capture ID. `DEMO-*` sample IDs will not verify.
7. In Resolve's `/docs`, authorize with your local Resolve token and call
   `POST /cases/{case_id}/paypal-capture-verifications`. Then inspect its saved
   history and the case's reconciliation. Use the same sandbox seller/app for
   checkout and verification.

Put the following fields in `backend/.env`, replacing placeholders locally.
Uncomment the fields from `.env.example` and set the enabled flag to `true` only
after filling them:

```dotenv
RESOLVE_PAYPAL_SANDBOX_ENABLED=true
RESOLVE_PAYPAL_RESOLVE_MERCHANT_ID=YOUR_RESOLVE_MERCHANT_UUID
RESOLVE_PAYPAL_SANDBOX_CLIENT_ID=YOUR_SANDBOX_APP_CLIENT_ID
RESOLVE_PAYPAL_SANDBOX_CLIENT_SECRET=YOUR_SANDBOX_APP_CLIENT_SECRET
RESOLVE_PAYPAL_SANDBOX_MERCHANT_ID=YOUR_SANDBOX_SELLER_MERCHANT_ID
```

Keep existing database configuration if you already have an `.env`. Sandbox login
email/password, REST app credentials, and the local Resolve bearer token have
different purposes; the client uses only the REST credentials for PayPal calls.

Setup references: [PayPal getting started](https://developer.paypal.com/api/get-started/)
and [sandbox accounts](https://developer.paypal.com/sandbox-testing/accounts/).
The [merchant ID instructions](https://developer.paypal.com/docs/multiparty/seller-onboarding/build-onboarding/)
also describe where to find the sandbox account's ID; partner onboarding from
that document is not required by this first-party client.

The first-party sandbox app is bound to exactly one Resolve merchant UUID in
configuration. Other merchants cannot borrow its credentials. This does not yet
implement partner onboarding or per-merchant credential storage.

### Verification endpoints

- `POST /cases/{case_id}/paypal-capture-verifications` reads the case's capture
  and appends a verification observation. No request body or client-supplied URL
  is used. Authentication and case ownership are required.
- `GET /cases/{case_id}/paypal-capture-verifications` reads saved history for that
  merchant/capture, including after credentials are disabled.

Verification requires exact capture ID, original gross amount, currency, and
configured payee merchant ID. Unsupported currency, missing payee, malformed
provider JSON, or unknown statuses cannot produce a successful verification.
The official schema permits the payee field but does not guarantee it in every
response; this version refuses incomplete data instead of guessing. An order-read
fallback is future work.

Successful records distinguish `capture_details_verified=true` from
`refund_history_verified=false` and `refund_eligibility_verified=false`. Capture
status is reported as observed, including pending/refunded states. Verification
does not establish that a refund is permitted, confirm return evidence, or import
a complete refund history. Overall reconciliation/approval `verified_with_paypal`
therefore remains false.

The record is persisted, appears in reconciliation, contributes to its state
fingerprint, and invalidates existing approvals for that payment. The external
read happens outside the database write transaction; the backend rechecks the
case's payment before saving the result. Provider errors never create a successful
observation or overwrite payment amounts.

`checked_at` is the server save time of a historical observation. Saved evidence
does not expire automatically and must be refreshed before future execution.

Disabled/incomplete configuration returns `503`; a different configured Resolve
merchant returns `403`; missing captures return `404`; amount/payee mismatches
return `409`; invalid capture ID syntax returns `422`; malformed/denied provider
reads return `502`; unavailable/rate-limited provider returns `503`; timeout returns
`504`. Raw provider error bodies and secrets are not returned.

Real sandbox verification requires your own app credentials and a sandbox payment.
The configured app's OAuth exchange was checked successfully against PayPal Sandbox
on 2026-11-07. Subsequently its capture client read the owner's USD 1.00 test
capture, matching ID, original amount, currency and configured seller, with observed
status COMPLETED. This direct client check did not create a case or save a provider
observation at that point. The authenticated case-route and full-refund checks
subsequently passed, as recorded in the execution section below.
Follow the [manual test purchase walkthrough](../docs/SANDBOX_TEST_PURCHASE.md) to
create a sandbox order, approve it as a buyer, capture it, and verify it in Resolve.
The owner reported completing the manual purchase. The assistant read its capture
but did not send any order-creation or capture-write request.
Local simulation results establish caller behavior against fixtures, not a real
PayPal account. See the [simulation guide](../postman/README.md).

## Local database

On startup, the initial versioned SQL migration creates `backend/data/resolve.sqlite3`
if needed. Records survive reloads and restarts. Importing the app alone does not
create the database.

The optional `RESOLVE_DATABASE_PATH` setting accepts a local file path, either in
the environment or in `backend/.env`; see `.env.example`. Relative paths resolve
from the backend directory, independently of the terminal working directory.

SQLite is the local development database for this milestone. Supabase/PostgreSQL
remains a future integration and is not configured by this setting. Storage uses
Python's built-in `sqlite3` module, so no database account or extra package is needed.

Payments and refunds store integer cents; the API still uses decimal strings.
Refund validation and writes share a `BEGIN IMMEDIATE` transaction so separate
app instances using the same file cannot independently reserve the same balance.
Reconciliation reads one consistent transaction snapshot. Lock contention exceeding
the wait timeout returns `503`.

Schema version 8 is recorded in SQLite's `user_version`. Startup applies the
initial, merchant-ownership, refund-approval, capture-verification, durable
execution/refund-evidence, provider-identity, case-event/condition-epoch, and
refund-history/case-lifecycle migrations
atomically as needed. Version-1
records are preserved as described above. An unknown newer version fails startup
instead of resetting it. Future schema changes need new migrations.

Old in-memory records are not automatically imported. Databases and `.env` files
are ignored by Git. Stop the server before copying the file for a local backup.
Keep the file on local disk; this is not a multi-host or network-filesystem setup.

## API contract

- `POST /health`: public development health check.
- `GET /auth/me`: authenticated merchant identity.
- `POST /cases`: create a case; returns `201` with an ID and status `open`.
- `GET /cases`: owned case page with `limit`, `offset`, and optional `capture_id`.
- `GET /cases/{case_id}`: retrieve a case; returns `404` when no case matches.
- `PUT /cases/{case_id}/commitment`: revise a commitment using the current state fingerprint.
- `GET /cases/{case_id}/timeline`: recorded payment/case history, paginated and merchant-scoped.
- Invalid input returns `422`.

Case responses include server-assigned `merchant_id`. Condition-check responses
include `recorded_by_merchant_id`; neither field can be supplied in its create
request. These identify the authenticated merchant, not a verified PayPal account.

## Merchant refund approvals

Approvals record merchant consent to an exact refund against the current local
case state. They do not execute refunds or establish PayPal eligibility.

1. Review `GET /cases/{case_id}/reconciliation`, including its `state_fingerprint`.
2. Submit the exact recommended amount, capture, currency, and fingerprint below.
3. Retrieve the approval, or revoke it before a future executor uses it.

`POST /cases/{case_id}/refund-approvals` accepts:

```json
{
  "request_id": "8fdf964d-a1b0-4870-978c-9ba28ed076c0",
  "capture_id": "DEMO-CAPTURE-001",
  "amount": "80.00",
  "currency": "USD",
  "state_fingerprint": "replace with the 64-character reconciliation fingerprint",
  "decision_note": "Approve the remaining refund after reviewing the return."
}
```

Use a new UUID for each new decision. Replace the fingerprint placeholder with
the actual value. The server rechecks agreement, conditions, pending refunds,
amount, currency, capture, and fingerprint in the transaction saving the approval.
An ineligible case, stale state, or existing active approval returns `409`.

| Endpoint | Behavior |
| --- | --- |
| `POST /cases/{id}/refund-approvals` | Save approval; `201` initially, `200` for an identical replay. |
| `GET /cases/{id}/refund-approvals` | List the case's approval records. |
| `GET /cases/{id}/refund-approvals/{approval_id}` | Retrieve the approval and saved reconciliation basis. |
| `POST /cases/{id}/refund-approvals/{approval_id}/revoke` | Revoke with `{"reason": "Changed my decision"}`. |
| `GET /cases/{id}/refund-approvals/{approval_id}/events` | Read approval, revocation, expiry, and invalidation events. |

The server sets the approving merchant, approval ID, and 15-minute expiry. Only
one approval is active per merchant/capture, including across cases. New refund
observations, changed refund status, new condition checks, and successful PayPal
capture observations invalidate active
approvals for that capture within the same transaction. Identical refund replays
and repeated same-status updates do not invalidate approvals.

Approval reads persist expiry events they discover. Expired, revoked, and
invalidated records remain visible. Replaying their original request returns the
terminal record without reactivating it. A fresh decision needs a new request UUID;
a different body with an existing UUID returns `409`. Identical revocation retries
are idempotent.

The approval stores an immutable local state snapshot and event history. It does
not change refund totals. The bounded sandbox executor rechecks exact consent and
provider state, reserves one durable full-refund action, and reuses its persisted
PayPal request ID on recovery. Claimed approvals cannot be revoked to cancel an
already submitted action. All approval routes require authentication and
return `404` for foreign cases or approval IDs.

New case requests require a `payment` object. A `commitment` may be omitted or
`null`, because a complaint can exist before a remedy has been proposed.

```json
{
  "order_id": "ORDER-001",
  "complaint": "My refund is incomplete.",
  "payment": {
    "capture_id": "DEMO-CAPTURE-001",
    "captured_amount": "100.00",
    "currency": "USD"
  },
  "commitment": {
    "amount": "100.00",
    "currency": "USD",
    "source_message": "We will refund the full $100 after receiving your return.",
    "condition": "Return must be received",
    "status": "accepted"
  }
}
```

### Validation rules

- This first version supports USD only; both currency fields default to USD.
- Monetary values use `Decimal`. Send decimal strings, such as `"100.00"`.
- Amounts must be finite, greater than zero, and have at most 12 significant
  decimal digits, including at most two fractional digits.
- A refund commitment is the total agreed refund, not an additional refund. It
  cannot exceed the submitted captured amount and must use the same currency.
- A commitment defaults to `proposed`; `accepted` records an agreement, not
  authorization to execute a refund.
- An optional condition is recorded as text. Manual checks and evidence notes
  can be recorded through the condition-check endpoints below.
- Required text is trimmed and cannot be blank. Unknown fields are rejected,
  including within payment and commitment objects.
- Monetary values are serialized as JSON strings in responses.

These checks validate submitted data. Merchant authentication protects local
records; explicit approval records and scoped sandbox capture verification are
supported. Verified order history is scoped to one supported PayPal Sandbox capture;
the application does not claim merchant-wide reporting coverage.

## Sandbox refund execution and provider observations

Read [the execution contract](../docs/REFUND_EXECUTION.md) for request bodies,
state transitions and recovery. Set `RESOLVE_PAYPAL_SANDBOX_REFUNDS_ENABLED=true`
locally only to opt into sandbox writes; capture reads must also be enabled.
The default is false, and production hosts are not configurable.

By default execution supports the first full refund only. With
`RESOLVE_PAYPAL_SANDBOX_PARTIAL_REFUNDS_ENABLED=true`, refresh order history
before approval, then approve an exact amount up to the current recommendation.
Resolve re-reads history before executing and rejects stale approvals or gaps.
PayPal's response remains the authority on actual acceptance.

Execution states are `reserved`, `submitting`, `unknown`, `pending`, `completed`,
and `failed`. Inspect the returned status: creating an execution record is not
proof that a refund completed. An unknown outcome retains a capture hold with
`execution_pending` / `monitor_refund_execution` and zero recommendation, without
inventing a completed/pending refund. Manual ledger writes are blocked during
the hold. Recorded provider refund status must be refreshed from PayPal.

Retries reuse the same saved provider UUID, body, client identity and seller.
The 60-second worker lease and 24-hour recovery POST limit prevent competing
submissions and retries outside this version's supported window. A prior unknown
outcome stays unknown when a later retry is rejected. `refresh` may receive a
known `refund_id` to reconcile an unknown action by a provider read instead.

Provider refund observations are exposed separately and included in the latest
reconciliation evidence. Their individual `refund_details_verified=true` does
not assert complete refund history or general eligibility; overall verification
remains false. Projection, approval invalidation, execution events and observation
history commit together. A failure after a provider request retains recoverable
state rather than reporting a fictitious failed refund.

On 2026-11-07, the existing USD 1.00 sandbox test completed through the actual
authenticated routes: exact test approval, one refund POST, independent refund
GET, capture status REFUNDED and reconciliation fulfilled. A temporary key/server
were cleaned up, and the write flag was enabled only inside that test process.
The test commitment was explicitly synthetic; no customer conversation was invented.

## Case workspace and recovery worker

Use the [workflow guide](../docs/PAYPAL_RECONCILIATION.md) for attachment uploads,
close/reopen, the review queue, and webhook registration and processing.

See [backend operations](../docs/BACKEND_OPERATIONS.md). A case can start without
a commitment, then receive a proposed/accepted revision using the current
reconciliation fingerprint. Different stale changes return `409`; an identical
commitment is an idempotent no-op. Amount/currency remain constrained by the
capture. Changed conditions start a new evidence epoch, preserving old checks
without reusing them to satisfy the revised condition. Active executions block
financial commitment changes.

The timeline combines durable case/manual-refund changes with existing approval,
execution, condition and provider-observation history. It preserves source case
IDs within the owner's shared capture and never fabricates legacy timestamps.
Actor labels identify the merchant account, system, or unknown legacy actor;
they do not establish a particular person's identity. Response pages are bounded;
the current local timeline assembles a capture's recorded history before slicing.

```powershell
uv run python -m app.worker --once
uv run python -m app.worker --loop --interval 30 --limit 20
```

The trusted local worker recovers only the configured merchant's existing
reservations. It creates no agreement or approval, observes backoff/leases and
the recovery window, and can refresh pending known refunds while writes are
disabled. It is not installed as a system service or hosted scheduler.

Regenerate the reusable contract after API/model changes:

```powershell
uv run python scripts/export_openapi.py
```

Output: [Resolve OpenAPI](../postman/contracts/resolve.openapi.json). Exporting does
not start a server or initialize the database. It exports public schema definitions,
not local credentials or case records.

## Refund tracking and reconciliation

The refund and condition submission routes in this section accept manual local
development data. Provider observations/executions use their separate routes above.
Recording a manual refund does not execute one. Accepted commitments
and positive recommendations do not authorize a financial operation.

| Endpoint | Behavior |
| --- | --- |
| `POST /cases/{id}/refunds` | Record a refund observation; `201` for a new refund, `200` for an identical replay. |
| `GET /cases/{id}/refunds` | List the payment's refund records, shared across cases referencing the same capture. |
| `PATCH /cases/{id}/refunds/{refund_id}` | Update a pending refund to `completed` or `failed`. |
| `POST /cases/{id}/condition-checks` | Record a manual `met` or `not_met` condition check with an evidence note. |
| `GET /cases/{id}/condition-checks` | Retrieve that case's condition-check history. |
| `GET /cases/{id}/reconciliation` | Calculate totals, outstanding commitment, and the next step from recorded data. |

### Record a refund

```json
{
  "refund_id": "DEMO-REFUND-001",
  "capture_id": "DEMO-CAPTURE-001",
  "amount": "20.00",
  "currency": "USD",
  "status": "completed"
}
```

Refund statuses are `pending`, `completed`, and `failed`. Refund IDs are unique
within the merchant's ledger. Identical replays return the existing record; a replay
with different details returns `409`. Changes to status use the PATCH endpoint:

```json
{"status": "completed"}
```

Pending refunds can become completed or failed. Terminal states cannot be changed;
repeating the current status is allowed. Capture, amount, and currency are immutable.
The record must reference the case's capture, and completed plus pending refunds
cannot exceed the capture amount. Failed refunds consume no balance. Conflicting
records return `409`; invalid field values return `422`. Missing cases or refunds
return `404`.

The same merchant's cases sharing a capture must agree on its amount and currency. They see the same
refund history, so opening another case does not reset that payment's balance.

### Record a condition check

For the sample return condition, submit:

```json
{
  "status": "met",
  "evidence_note": "Development example: warehouse return record RETURN-001 confirms receipt."
}
```

Checks record the authenticated merchant ID, are timestamped, and are preserved in order.
Legacy checks retain an unknown actor rather than inventing one. The latest check determines the
recorded condition state. A case without a condition returns `409` when a check
is submitted. This is manual evidence recording, not independent verification.

### Reconciliation rules

- Completed refunds reduce the outstanding commitment.
- Pending refunds reserve capture balance but do not count as completed remedies.
- Failed refunds consume no balance and do not fulfill commitments.
- `outstanding_commitment_amount` includes amounts still pending.
- `uncovered_commitment_amount` subtracts both completed and pending refunds from
  the committed total and is floored at zero.
- `remaining_refundable_amount` subtracts completed and pending refunds from the
  captured amount. It is based only on the local records, not PayPal eligibility.
- `recommended_refund_amount` is zero until an agreement is accepted, any condition
  is recorded as met, and no refund is pending. It is a suggested amount to review,
  not an executable action or authorization.
- Outstanding amounts are `null` if there is no commitment.
- Reconciliation does not close the case or mutate its agreement status.

| Situation | Reconciliation status | Next action |
| --- | --- | --- |
| No commitment | `no_commitment` | `review_complaint` |
| Reserved, submitting, unknown or pending execution | `execution_pending` | `monitor_refund_execution` |
| Terminally failed first full-refund execution | `execution_failed` | `review_failed_execution` |
| Proposed commitment | `awaiting_acceptance` | `confirm_agreement` |
| Accepted commitment, a refund pending | `refund_pending` | `monitor_pending_refund` |
| Accepted commitment fully refunded, no pending refund | `fulfilled` | `none` |
| Accepted commitment, outstanding amount, condition not met or unchecked | `awaiting_condition` | `verify_condition` |
| Accepted commitment, outstanding amount, condition met or absent, no pending refund | `refund_required` | `request_merchant_approval` |

With an accepted $100 commitment, a recorded satisfied condition, and $20 completed,
the outstanding and recommended amounts are $80. If a further $80 is pending,
the outstanding amount stays $80 but the recommendation is $0. If that pending
refund fails, the recommendation becomes $80 again. A completed refund can fulfill
an accepted commitment even if a prior condition was not checked; it has already
been paid according to the submitted records.

## Tests

```powershell
uv run python -m pytest
```

The default tests exercise the local FastAPI application with PayPal disabled.
The separate [HTTP simulation tests](../postman/README.md) are skipped unless
explicitly enabled behind the local proxy. Neither test suite contacts real
PayPal or an AI provider. Each test uses its own temporary database; tests do not clear the
development database. Persistence checks reopen the file in new app instances
and a separate Python process. Concurrency checks use independent stores sharing
one local file.
