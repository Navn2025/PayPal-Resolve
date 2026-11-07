# Resolve project status

Updated: 2026-11-07.

The backend now handles case lifecycle, evidence attachments, exception review,
verified Sandbox webhook intake, and order-scoped refund discovery. Partial
and multiple Sandbox refunds require fresh history and separate exact approvals.
See the [workflow guide](PAYPAL_RECONCILIATION.md).

The [resolution workspace](RESOLUTION_WORKSPACE.md) adds several promises
per case, tracked independently and optionally connected by prerequisites.
Cases can cover non-refund remedies without a captured payment. Provider evidence
adapters use PayPal Sandbox, Shopify Admin GraphQL and EasyPost. Only the existing
approved refund path submits money movement; the new routes read evidence.

The [merchant UI](../frontend/README.md) presents the case inbox, evidence
timeline, approvals, separate Sandbox submission, review queue, and buyer
receipt. The public homepage offers a separate demo and buyer entry point.
The live workspace requires [merchant sign-in](MERCHANT_SIGN_IN.md) with a
Resolve key or an explicitly linked PayPal account. The latter needs provider
configuration and has passed local simulation only.

The [customer portal](CUSTOMER_PORTAL.md) uses a private, revocable case link
to show the customer-facing summary and conversation, without merchant login.
The [intake and triage workflow](CUSTOMER_WORKFLOW.md) lets customers report an
order issue and upload evidence. The same link shows the milestone timeline,
next actor, and overdue deadline. Merchants can assign cases, filter the whole
inbox, and mark displayed messages read. Payment records can be linked to
the same case when a refund is agreed.

The optional [follow-up integrations](HOSTED_FOLLOWUP.md) add queued Resend
notifications, email sign-in and My cases, scheduled provider refreshes, and
a read-only Zendesk ticket link. They are configured separately from the local
demo. A genuine PayPal Sandbox delivery still needs a reachable registered HTTPS
callback; simulated verification does not establish live delivery.

The [PostgreSQL driver and importer](POSTGRES_MIGRATION.md) support the API,
merchant CLI and workers. The existing SQLite records were copied and
verified on an isolated local PostgreSQL instance. A later read-only check of the
configured PostgreSQL database identified a migration 003 checksum mismatch.
Migration 004 adds the missing PayPal callback claim column on the next restart.

## Account-backed result

The existing **USD 1.00 sandbox purchase was refunded in full** through the actual
authenticated Resolve endpoints. One financial POST was observed. An independent
refund GET reported COMPLETED, the capture reported REFUNDED, and reconciliation
reported fulfilled with zero remaining/recommended amount. This was explicitly
labelled as an automated sandbox demonstration, not a customer support agreement.

| Record | ID |
| --- | --- |
| Original capture-only case | `df7f9710-e3ee-4850-8362-d974424409ae` |
| Full-refund demonstration case | `bb41ba9c-9a29-44a2-b961-76fc41ef5e7c` |
| Refund execution | `71a96df7-3102-4ad3-8b86-9646b3756bdd` |
| PayPal sandbox refund | `5RW33931WF076894P` |

Temporary access keys were revoked and temporary test servers stopped. The
owner's existing key was preserved. Once the backend is running, use
[local API docs](http://127.0.0.1:8000/docs). Refund writes default to disabled.
No additional financial POST was made during the later restart/replay checks.
The history reconciler also discovered that existing refund from the real
Sandbox order, verified it independently, and reported USD 0.00 remaining.
That check used an isolated database and only read PayPal.

## Review the result

Authorize in `/docs` with the existing private Resolve token, then inspect:

1. `GET /cases?capture_id=89E28779G1872370R` for the two related cases.
2. `GET /cases/{id}/reconciliation` for the full-refund demonstration case.
3. `GET /cases/{id}/timeline` for capture, approval, execution and refund history.
4. `GET /cases/{id}/refund-executions` and the execution events endpoint.

The stored timeline currently includes 9 timestamped events for this capture.
Legacy events without recorded timestamps are not fabricated. Case status remains
`open`; `fulfilled` is the calculated agreement outcome, not automatic case closure.

## Verification

- The frontend type check, production build, and all **14 browser tests**
  passed with 33 mocked requests and zero pass-through. They cover the public
  pages, key sign-in, simulated PayPal login and buyer intake, evidence,
  triage, timeline, email sign-in, and revocation.
- **242 SQLite tests passed**; 55 opt-in tests were skipped by default.
  A populated synthetic schema-10 database upgraded to version 11 and
  preserved its existing customer link, message, and foreign keys in the
  earlier triage milestone. A synthetic version-11 database upgraded to
  version 12 with its existing invite still usable.
- **3 follow-up HTTP simulation tests passed**, with 33 mocked requests and
  zero pass-through. They cover email retry, webhook reconciliation, scheduled
  proof reads and Zendesk status.
- **51 PostgreSQL integration tests and 13 provider simulations on PostgreSQL
  passed** in the migration milestone. Eight targeted PostgreSQL tests passed
  after the startup fix. Three authentication tests passed with the PayPal
  simulation in the sign-in milestone (13 mocked requests, zero pass-through).
- **45 HTTP simulation tests passed**, with 336 mocked requests and zero passed-through requests. The
  suite covers the earlier refund and webhook workflows plus the multi-remedy
  case, conditional refund, tracking, cancellation, subscription, credit,
  exchange, billing correction and dispute evidence.
- Actual sandbox validation is the USD 1.00 flow above; it does not replace the
  broader local/simulation failure coverage.
- Case pages/timeline/reconciliation and completed execution replay passed after
  restarting with writes disabled. The recovery CLI ran with an empty queue and
  zero errors/remaining reconciliation work.
- Ruff formatting and focused Python F checks passed. Postman's local mock
  generator checked both the Resolve and PayPal OpenAPI contracts. A populated
  version-8 copy migrated to version 9 with its execution and audit data intact.
- Source/current database scans found no raw configured PayPal app credentials;
  runtime data, local reports, backups, `.env` and simulation logs remain ignored.

The known Starlette TestClient/HTTPX deprecation warning remains. uv uses this
project's environment despite a warning about an unrelated inherited VIRTUAL_ENV.

## Boundaries and next engineering work

Supported history is limited to the configured Sandbox app and orders with one
USD capture. Verify actual signed delivery on an HTTPS Sandbox registration and
exercise a separate account-backed partial-refund purchase before widening the
scope. Verify the deployment and the PayPal login return URL with a real
Sandbox app. Merchant-wide history, AI extraction/evaluation and distinct
merchant team roles remain future work.

Use [backend operations](BACKEND_OPERATIONS.md) for revision/timeline/worker
commands, [execution/recovery](REFUND_EXECUTION.md) for financial boundaries,
and [the engineering log](ENGINEERING_LOG.md) for implementation decisions,
validation details and preserved history. No commits, pushes or deployments were made.
