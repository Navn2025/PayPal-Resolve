# Sandbox refund execution

## Contract and scope

Resolve supports merchant-approved USD Sandbox refunds. Amount and currency are
explicit in every provider request. Enable the separate partial-refunds flag to
use the verified order history workflow described in
[PayPal reconciliation](PAYPAL_RECONCILIATION.md).

Execution always requires an open owned case, Sandbox reads and writes enabled,
and a live exact-state approval. The first-full path also requires an empty
ledger, saved capture evidence and a fresh COMPLETED capture read. The
history-gated path requires consistent order/capture/refund records and an exact
approved amount within both the outstanding commitment and verified balance.
PayPal decides whether the actual request is accepted.

| Route | Contract |
| --- | --- |
| `POST /cases/{case_id}/refund-executions` | `{request_id: UUID, approval_id: UUID}`; reserve once, submit, and return durable outcome; identical replays return existing execution. |
| `GET /cases/{case_id}/refund-executions` | List execution records for this case. |
| `GET /cases/{case_id}/refund-executions/{id}` | Inspect status, request identity, provider result and final capture check. |
| `POST /cases/{case_id}/refund-executions/{id}/retry` | Recover reserved/unknown or stale submitting work, reusing the exact saved PayPal request ID/body. |
| `POST /cases/{case_id}/refund-executions/{id}/refresh` | Read a known refund from PayPal and project its latest status; optional `{refund_id: string}` supports read-only reconciliation of an unknown action; no financial POST. |
| `GET /cases/{case_id}/refund-executions/{id}/events` | Ordered immutable execution history. |
| `POST /cases/{case_id}/paypal-refund-verifications` | `{refund_id: string}`; independently read a known refund and require its parent capture link to match. |
| `GET /cases/{case_id}/paypal-refund-verifications` | Saved provider refund observations for the owner's capture. |

All routes require normal merchant bearer authentication. Missing/foreign
resources are `404`. Invalid inputs are `422`. State/ownership-of-approval,
amount, concurrent-lease and stale-state conflicts are `409`.
Disabled settings are `503`. A submitted request returns the execution record,
including unknown/failed outcomes; callers must inspect status rather than infer
success from HTTP status. New execution records return `201`, replays `200`.

## Durable state and concurrency

States: reserved -> submitting -> pending/completed/failed/unknown. A request UUID
is unique within the merchant. The execution owns one approval and one capture;
one active execution per capture prevents competing actions across cases.
Reservation snapshots exact consent and final capture evidence in one SQLite
transaction. Network calls occur outside the writer transaction.

A 60-second submission lease prevents concurrent local workers from sending the
same operation. Unknown outcomes retain a capture-wide hold and use the original
PayPal request UUID on recovery, never a newly generated identity. Replays do not
submit again. A hash of app client ID, expected seller and sandbox scope binds
the idempotency identity; changing the app/seller blocks financial retries, while
rotating a secret for the same app does not. Old records without this identity
may only be read-reconciled. A later rejection cannot clear a prior unknown
outcome, and stale workers cannot erase a newer submission lease.
Recovery POSTs are bounded to 24 hours from reservation, within
PayPal's documented refund idempotency period; after that, a known refund can be
read but an unidentified outcome requires operator reconciliation.

Known pending/completed/failed provider refunds project into the shared local
ledger atomically with execution events and provider observation history. An
unknown request is not recorded as a completed or failed refund. Its hold blocks
new recommendations/approvals and conflicting manual ledger writes. Provider-
managed refund status is refreshed from PayPal rather than manually overwritten.
Revocation cannot cancel an already claimed provider action.

## Evidence and validation

Use the existing Postman TLS proxy simulation with stateful refund fixtures for
success, provider rejection, pending-to-completed, timeout after the provider
created a refund, malformed responses, retries, and concurrent calls. Verify
persisted request identity, one provider refund, no duplicate ledger projection,
restart recovery, stale approval rejection, atomic event rollback and tenant
isolation. Existing read simulations remain part of regression validation.

Account-backed validation is limited to the existing USD 1.00 sandbox capture,
with an explicitly labelled test commitment and approval. No production payment
or real customer agreement is created. A temporary local access key is revoked
after checks, and the refund-write setting defaults to disabled outside that test
process. The account-backed exercise passed on 2026-11-07: one financial POST,
one independent refund read, COMPLETED refund, REFUNDED capture and fulfilled
reconciliation. The temporary key and server were cleaned up.

Provider sources: [refund endpoint](https://developer.paypal.com/api/payments/v2/captures-refund),
[refund lookup](https://developer.paypal.com/api/payments/v2/refunds-get),
[request idempotency](https://developer.paypal.com/api/rest/requests/), and
[idempotency semantics](https://developer.paypal.com/api/rest/reference/idempotency/).
