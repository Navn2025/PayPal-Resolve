# Local PayPal capture and refund simulation

The [hosted follow-up simulation](simulations/hosted-followup/hosted-followup.sim.yaml)
adds Resend and Zendesk to the existing proof adapters. From the repository root:

```powershell
$env:RESOLVE_RUN_FOLLOWUP_SIMULATION = '1'
$env:RESOLVE_RUN_PAYPAL_SIMULATION = '1'
postman simulation run postman/simulations/hosted-followup/hosted-followup.sim.yaml --proxy --lift "uv --directory backend run python -m pytest tests/test_hosted_followup_simulation.py -q" --output ndjson
```

The [follow-up context](simulations/hosted-followup/hosted-followup.context.yaml)
separates simulated email and evidence from unverified hosted permissions.

The [resolution workspace simulation](simulations/resolution-workspace/resolution-workspace.sim.yaml)
also runs the PayPal, Shopify, and EasyPost proof adapters with fake credentials.
It includes the original PayPal regressions. From the repository root:

```powershell
$env:RESOLVE_RUN_PAYPAL_SIMULATION = '1'
try {
    postman simulation run postman/simulations/resolution-workspace/resolution-workspace.sim.yaml --proxy --lift "uv --directory backend run python -m pytest tests/test_resolution_simulation.py tests/test_paypal_simulation.py tests/test_refund_execution_simulation.py tests/test_paypal_history_simulation.py -q" --output ndjson
} finally {
    Remove-Item Env:RESOLVE_RUN_PAYPAL_SIMULATION -ErrorAction SilentlyContinue
}
```

The [evidence contract subset](contracts/resolution-evidence.openapi.yaml)
describes the extra provider reads. The
[simulation context](simulations/resolution-workspace/resolution-workspace.context.yaml)
separates fixture evidence from account-backed permissions and observations.

Resolve's generated [application OpenAPI](contracts/resolve.openapi.json) is kept
separately from the upstream PayPal subset. Regenerate it with
`uv run python scripts/export_openapi.py` from `backend` after API/model changes.

This directory keeps the upstream contract subset, local stand-in, simulation,
and evidence record with the code. The backend itself runs through its actual
routes, HTTPX client, OAuth form encoding, TLS, timeouts, and SQLite writes.
The stand-in replaces only PayPal's HTTP endpoints.

## Run on Windows

Prerequisites: uv with the backend dependencies synced and Postman CLI 1.82.0
(the version tested here). No Postman sign-in, real PayPal credentials, or sandbox
account is needed for this local command. Run from the repository root:

```powershell
$env:RESOLVE_RUN_PAYPAL_SIMULATION = '1'
try {
    postman simulation run postman/simulations/paypal-read/paypal-read.sim.yaml --proxy --lift "uv --directory backend run python -m pytest tests/test_paypal_history_simulation.py tests/test_paypal_simulation.py tests/test_refund_execution_simulation.py -q" --output ndjson
} finally {
    Remove-Item Env:RESOLVE_RUN_PAYPAL_SIMULATION -ErrorAction SilentlyContinue
}
```

`--lift` supplies its child process with the local proxy and temporary CA
certificate and stops the simulation when the tests end. The test fixture injects
that proxy into a real HTTPX client and trusts this CA. It retains the client's
fixed sandbox URL and does not disable TLS validation. Normal application clients
ignore environment proxies and keep `trust_env=False`.

The simulation must show OAuth and capture requests routed to the `paypal`
member and **zero passed-through requests**. The timeout fixture deliberately
waits longer than the client's timeout; its late mock response can appear after
the assertion that Resolve returned `504`.

## Files and contract boundary

- [Upstream contract subset](contracts/paypal-capture-read.openapi.yaml): OAuth,
  capture GET, approved capture-refund POST, refund GET, order history and webhook
  signature postback. The historical file
  and simulation names are retained for existing commands.
- [Stand-in configuration](mocks/paypal-sandbox/config.yaml) and
  [handler](mocks/paypal-sandbox/default.js): synthetic credentials, records,
  missing fields, mismatches, errors, redirect, and delayed response fixtures.
  Refund fixtures retain request identity and simulated provider state, including
  a timeout after refund creation. Unmodeled endpoints return `501`; checkout
  writes are not modeled. `/__resolve_test/state/{capture_id}` is a harness-only
  counter endpoint and `/__resolve_test/external/{capture_id}` creates simulated
  external refunds. Neither endpoint is used by the application or sent to PayPal.
- [Simulation](simulations/paypal-read/paypal-read.sim.yaml): intercepts
  `api-m.sandbox.paypal.com` only.
- [Evidence and unresolved assumptions](simulations/paypal-read/paypal-read.context.yaml):
  separates documented provider behavior from locally demonstrated caller behavior.
- [Integration tests](../backend/tests/test_paypal_simulation.py): real HTTP
  requests with fake values, plus resulting API responses and database state.
- [Refund HTTP tests](../backend/tests/test_refund_execution_simulation.py): full
  execution, replay, restart/recovery with the same request ID, pending refresh,
  denial, malformed response and parent-link checks.
- [History and webhook HTTP tests](../backend/tests/test_paypal_history_simulation.py):
  discovery of an external refund, repeated exact-amount partial refunds, hidden
  records, stale approval, webhook verification and duplicate delivery, reversal
  hold, and recovery by unique PayPal correlation without another refund POST.
- [Configuration checks](../backend/tests/test_paypal_config.py) and
  [storage checks](../backend/tests/test_paypal_storage.py): default-suite tests
  for no-network gates, tenant isolation, atomic rollback, and migration compatibility.
- [Local execution tests](../backend/tests/test_refund_executions.py) use explicitly
  synthetic provider DTOs for transaction failures, concurrency and lease/state
  invariants. They do not establish HTTP/provider behavior.
- The HTTP refund module also exercises the recovery worker refreshing a known
  pending refund while financial writes are disabled. Combined run: 40 tests
  passed, 276 mocked requests, zero passed through.

The contract was checked against PayPal's
[OAuth documentation](https://developer.paypal.com/api/rest/authentication/),
[capture-read reference](https://developer.paypal.com/api/payments/v2/captures-get),
and [primary Payments v2 specification](https://github.com/paypal/paypal-rest-api-specifications/blob/main/openapi/payments_payment_v2.json).
Orbit identified the capture-read operation but supplied only partial support
for the fields this caller needs: its saved example omitted payee. The official
schema/example includes payee, without guaranteeing it for every response. The
client requires `payee.merchant_id` and fails verification when absent.

### Merchant sign-in simulation

The same local Sandbox mock supports OAuth authorization-code exchange and
UserInfo for [merchant sign-in](../docs/MERCHANT_SIGN_IN.md). Run the focused
tests from the repository root:

```powershell
$env:RESOLVE_RUN_LOGIN_SIMULATION = '1'
try {
    postman simulation run postman/simulations/paypal-read/paypal-read.sim.yaml --proxy --lift 'uv --directory backend run --no-sync python -m pytest tests/test_merchant_auth.py -q' --output ndjson
} finally {
    Remove-Item Env:RESOLVE_RUN_LOGIN_SIMULATION -ErrorAction SilentlyContinue
}
```

This exercises the real Resolve HTTP client against the local mock. A browser
test also covers linking, sign-out, and PayPal sign-in with a simulated consent
redirect. Neither proves a registered Sandbox or live PayPal app is configured.

The CLI was signed out and the repo was not bound to a Postman workspace, so
owner-workspace mock search was skipped. This locally built stand-in is not an
owner-published PayPal mock. No artifacts were deployed or pushed to a workspace.

## What the evidence establishes

The local run demonstrates exact ID, decimal amount, currency and payee checks,
sanitized errors, refused redirects, a real timeout, persistence, approval
invalidation, and preservation of old evidence after a failed refresh. It does
not establish whether the user's app has the required scopes or returns payee,
whether any real capture exists, or whether a refund is eligible.

Capture details, complete refund history, and execution eligibility have separate
flags. Overall reconciliation remains `verified_with_paypal=false`; manually
entered refunds remain manual. See [first-time sandbox setup](../backend/README.md#first-time-setup)
to move from simulated evidence to an account-backed sandbox check.

Separately, on 2026-11-07 the application's real OAuth request to PayPal Sandbox
succeeded with a nonempty Bearer token and positive expiry. This is credential
acceptance evidence only, outside the simulation. A subsequent direct application
client check (CHG-010) read one actual sandbox capture and matched its ID, USD 1.00
amount, currency and configured seller; observed status was COMPLETED. No Resolve
case or verification observation was saved by that check. The authenticated
case-route check subsequently passed in CHG-011. CHG-013 completed a real sandbox
USD 1.00 full-refund exercise through actual HTTP routes: one financial POST,
independent refund GET, REFUNDED capture and fulfilled reconciliation. This is one
sample; complete refund history, partial execution and general eligibility remain
unimplemented. See [execution and recovery](../docs/REFUND_EXECUTION.md).
