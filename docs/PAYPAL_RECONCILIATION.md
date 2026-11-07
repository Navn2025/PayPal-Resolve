# PayPal Sandbox reconciliation and case workflow

## Refresh history and refund the remaining amount

1. Use a case with its actual PayPal Sandbox order and capture IDs. The order must have one purchase unit and one capture for the configured Sandbox seller, in USD.
2. Call `POST /cases/{case_id}/paypal-refund-history/refresh` with the merchant bearer key. This is a read of PayPal. It discovers refunds in the order, verifies every refund by ID and parent capture, compares completed totals against the cumulative provider amount, and reserves pending amounts. The response includes the checked time, scope, refund IDs, and remaining amount.
3. Enable `RESOLVE_PAYPAL_SANDBOX_REFUNDS_ENABLED=true` and `RESOLVE_PAYPAL_SANDBOX_PARTIAL_REFUNDS_ENABLED=true` locally if you intend to move Sandbox funds. Both default to false.
4. Read `GET /cases/{case_id}/reconciliation`. Use its current fingerprint to approve an exact amount up to the recommendation. Then submit a new execution using that approval. After an execution, refresh history and get a new approval for a subsequent amount.

Reconciliation exposes `paypal_refund_history` and `paypal_history_current`. The
saved snapshot is current for at most five minutes and can become stale sooner
if conflicting local or provider evidence arrives. The execution checks PayPal
again before reservation. If history changed, the old approval cannot authorize
the new state. Pending refunds, active executions and evidence conflicts block a
new execution. Failed/cancelled refunds do not consume balance.

This verifies the records visible for the supported order and app. It does not
provide a merchant-wide transaction feed or a provider-side lock. An external
refund can race the final POST; PayPal enforces its own remaining balance and
may reject the exact amount. See the [Orders read](https://developer.paypal.com/api/orders/v2/orders-get)
and [refund request](https://developer.paypal.com/api/payments/v2/captures-refund)
contracts. Unknown outcomes retain a capture hold. A
history-gated retry first looks for Resolve's unique `custom_id` in PayPal's
records; when the balance changed and no match is found, it blocks another POST.
Use the execution's read-only refresh with a known PayPal refund ID to recover
an outcome. An unrelated refund of the same amount cannot identify the action.

## Receive Sandbox webhooks

Register the HTTPS URL ending in `/webhooks/paypal/sandbox` on the same
Sandbox REST app. Subscribe to `PAYMENT.CAPTURE.REFUNDED`,
`PAYMENT.REFUND.PENDING`, `PAYMENT.REFUND.FAILED`, and
`PAYMENT.CAPTURE.REVERSED`. Put the registration ID in
`RESOLVE_PAYPAL_SANDBOX_WEBHOOK_ID` and restart the API.

Resolve sends the original event and signature headers to PayPal's verification
endpoint. Only a verified delivery is acknowledged and recorded. Identical
event IDs and payloads are deduplicated; a different payload for an existing
verified ID is rejected. The inbox stores the digest, event type, matching
identifiers and processing state; it does not retain the full event or signature.

From `backend`, run `uv run python -m app.worker --loop` alongside the API.
Processing is read-only for webhook work. The worker also recovers existing
approved execution records according to their settings and recovery rules.
It re-reads PayPal before projecting a refund; reversal notices are held for
review. A retry that cannot reconcile a delivery eventually becomes an exception.
An authenticated history refresh can clear a matching history exception when
the provider records agree.

PayPal's [Webhook Simulator](https://developer.paypal.com/api/rest/webhooks/simulator/)
does not produce events suitable for postback
verification. Use an actual Sandbox event with the REST app's registration to
validate the public delivery path. The local Postman simulation exercises the
protocol with synthetic events and fake credentials.

## Manage a case

| Action | Endpoint |
| --- | --- |
| Attach evidence | `POST /cases/{case_id}/attachments?filename=receipt.pdf`; send raw bytes with the matching PDF, PNG or JPEG content type |
| List and download | `GET /cases/{case_id}/attachments`; append `/{attachment_id}` to download |
| Close or reopen | `POST /cases/{case_id}/close` or `/reopen` with `{"reason":"..."}` |
| Review exceptions | `GET /review-queue?status=open`; also supports `status=resolved`, `limit`, and `offset` |
| Resolve a review item | `POST /review-queue/{exception_id}/resolve` with `{"reason":"..."}` |

Attachments are immutable, scoped to the case, and capped at 2 MiB each and
20 per case. Resolve checks the file signature and returns the bytes as a
download. Closure blocks workflow writes and invalidates consent for that case.
An active or uncertain execution must be reconciled before closure; read-only
provider evidence can still be updated after closure. Closing a case does not
settle a payment or fulfill a commitment.

Review items include failed/unknown executions and PayPal evidence exceptions.
A review note can acknowledge a known execution failure or an unmatched event
without a capture. It cannot clear an active execution or override conflicting
provider evidence. A confirmed reversal requires investigation outside this
refund workflow.
