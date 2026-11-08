# Local PayPal capture and refund simulation

Automatic investigations add generated list/review routes to
`contracts/resolve.openapi.json`. Their isolated evaluation uses the real
provider adapters with loopback HTTP stand-ins in
`backend/app/synthetic_investigations.py`, plus a bounded PayPal read simulation
in `backend/tests/test_investigations.py`. Run
`uv run python scripts/isolated.py -m pytest tests/test_investigations.py -q`
from `backend`. This path needs neither Postman authentication nor real provider
keys. It proves local contracts and guardrails, not live provider/model quality.
Existing financial simulations below retain their original scope. See
[model routing and evaluation](../docs/AI_INVESTIGATIONS.md).

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

## Resolve Evidence SDK acceptance test

From the repository root, after installing the SDK's build dependencies:

```powershell
$env:RESOLVE_RUN_SDK_EVIDENCE_SIMULATION = '1'
try {
    postman simulation run postman/simulations/paypal-read/paypal-read.sim.yaml --proxy --lift 'npm --prefix sdk/typescript test' --output ndjson
} finally {
    Remove-Item Env:RESOLVE_RUN_SDK_EVIDENCE_SIMULATION -ErrorAction SilentlyContinue
}
```

The SDK talks to a disposable FastAPI/SQLite instance. The fixture seeds a
USD 25 external refund in the PayPal stand-in. The test checks approval and
confirmation as separate records, retries, buyer privacy, tenant isolation, and
the behavior when the provider goes down. The mock counters verify that this
flow did not submit a refund. This does not establish account-backed visibility.

## Commerce integration acceptance test

The same SDK simulation can read a real, disposable merchant app database
through the example PostgreSQL views. Set `RESOLVE_COMMERCE_TEST_APP_ADMIN_URL`
to a loopback PostgreSQL cluster reserved for tests. The test creates and removes
its own database and roles. Run the SDK acceptance command above with that
additional variable. It asserts that the app role cannot read a password or
write to a view, detects app vs PayPal refund differences, and observes no
financial POSTs from the commerce flow.

## Store checkout acceptance test

The [Field Brew example](../examples/checkout-store/README.md#verify-without-a-real-buyer)
uses this same PayPal simulation to approve a cart in Chromium, capture once,
sync the app order through the Resolve SDK, and detect a simulated outside
refund. Both databases are disposable. The approval controls are mock-only.

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

### Buyer Google sign-in simulation

The [buyer Google simulation](simulations/customer-google/customer-google.sim.yaml)
intercepts the Google token and public signing key endpoints. The tests register
locally signed ID tokens with ephemeral keys, require PKCE at code exchange, and
verify that invalid claims and replay cannot create a buyer session.

```powershell
$env:RESOLVE_RUN_GOOGLE_SIMULATION = '1'
try {
    postman simulation run postman/simulations/customer-google/customer-google.sim.yaml --proxy --lift 'uv --directory backend run --no-sync python -m pytest tests/test_customer_google.py -q' --output ndjson
} finally {
    Remove-Item Env:RESOLVE_RUN_GOOGLE_SIMULATION -ErrorAction SilentlyContinue
}
```

The browser spec `customer-google.spec.ts` also uses this simulation with
`RESOLVE_UI_GOOGLE_FIXTURE=1`. Its consent page is a browser fixture, so it does
not establish that any Google Cloud app is registered. SMTP is tested by a
separate loopback TLS fixture because it is not HTTP.

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
