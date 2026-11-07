# Backend operations and case workspace

## Implemented API contract

| Route | Behavior |
| --- | --- |
| `GET /cases?limit=20&offset=0&capture_id=...` | Merchant-owned case page, newest inserted rows first; optional exact capture filter. Limit 1-100, offset 0-100000. |
| `PUT /cases/{id}/commitment` | `{state_fingerprint, commitment}`. Validates the full commitment against the capture and current reconciliation fingerprint, saves revision evidence, and invalidates old approvals. |
| `GET /cases/{id}/timeline?limit=50&offset=0` | Recorded case/payment history for the owning merchant's shared capture, including original source case IDs. |

Authentication is the existing Resolve merchant token. Case/payment queries never
include another merchant's data. A missing/foreign case is `404`; stale changes
or an active execution are `409`; invalid request/amount/pagination is `422`.
Submitting the already-current commitment is an idempotent read/no-op. Different
updates require the current fingerprint from reconciliation.

Changing a commitment condition starts a new evidence epoch: previous condition
checks remain in history but do not satisfy the revised condition. No new physical
evidence or human action is fabricated. A new check is required. Captured amount,
currency and case ownership are not edited through this route.

Timeline entries retain source, actor account/system/unknown attribution, source
case and actual recorded UTC timestamp. New case/manual-refund/commitment changes
have durable events. Existing timestamped approvals, execution events, condition
checks and provider observations are included. Historical case creation/manual
refund changes without timestamps are not reconstructed. Ordering is UTC followed
by a deterministic event ID, not a claim of a global external event order.

## Local recovery worker

Run one bounded recovery pass from `backend`:

```powershell
uv run python -m app.worker --once
```

For a long-running local worker:

```powershell
uv run python -m app.worker --loop --interval 30 --limit 20
```

The trusted local worker uses only the configured merchant's already-reserved
executions. It cannot create commitments or approvals. Pending known refunds are
read/refreshed. Reserved/unknown or expired submission leases may be recovered
with the saved provider identity/body, within the supported POST window and only
when the refund flag is enabled. Short backoff prevents repeated immediate work;
active leases, identity mismatches and expired recovery windows are respected.
Writes-disabled mode can still refresh known pending refunds when reads are enabled.

Output contains counts and opaque record IDs/status codes, never credentials,
tokens, customer conversations or raw provider errors. A process stop does not
erase reservations. Multiple workers rely on the same database lease rules.

A failed first full-refund execution that leaves a commitment outstanding reports
`execution_failed` / `review_failed_execution`, rather than recommending another
approval for an already-claimed capture. Later verified refunds can still fulfill
the commitment; failed execution history does not erase money already returned.

Response pages are bounded. Timeline assembly currently reads the capture's
recorded history into memory before slicing; a deployed high-volume version needs
database-side pagination/aggregation. Historical rows are not assigned invented
creation times or actor identities.

This is a local process, not installed as an operating-system service or a hosted
scheduler. The same worker processes verified Sandbox webhook deliveries; see
[registration and processing](PAYPAL_RECONCILIATION.md). A hosted worker remains future work.
