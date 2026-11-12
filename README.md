# Resolve for PayPal

### From refund promise to verified resolution.
### 🔗 [Live demo → paypal-resolve.vercel.app](https://paypal-resolve.vercel.app)

Resolve is a payment aftercare platform for PayPal merchants. It connects customer-support commitments with payment records, identifies incomplete refunds, and helps merchants coordinate authorized remedies.

Its automatic investigation worker gathers linked evidence when case revisions
are queued, uses bounded model triage, and validates the proposed next step.
Fresh owned provider facts can satisfy a selected evidence read without another
request. This is an evidence workflow; investigation review never authorizes a
payment. A real Groq-backed investigation of the filmed completed Sandbox refund
has now been verified, alongside the controlled regression checks (CHG-060).

A successful payment does not always mean a successful purchase. Resolve helps buyers and merchants understand what was agreed, what has happened, and what still needs to be done.

> **Status:** The application uses real API-backed workspace and private buyer records. Product demo/sample modes have been retired; `/demo` redirects to sign-in. PayPal merchant identity and Google/email buyer identity are optional. Missing verification is displayed as unavailable. An explicitly authorized real USD 1 PayPal Sandbox order → buyer approval → capture → full refund was independently verified and persisted. This verifies that scoped Sandbox workflow; hosted production and other account-backed integrations remain unverified. Sandbox refund writes default to disabled.

The [resolution workspace](docs/RESOLUTION_WORKSPACE.md) can track several
promises in one case: refunds, returns, replacements, cancellation, subscriptions,
store credit/exchanges, billing corrections, and dispute handoff. PayPal, Shopify,
and EasyPost evidence reads are optional; refund execution remains the only
provider write.

For a responsive local preview, build once with
`npm --prefix frontend run build:preview`, then run
`npm --prefix frontend run preview` alongside the backend. This serves compiled
pages on port 3000 without development-time compilation. Rebuild after frontend
changes. See [performance and local preview](docs/PERFORMANCE.md).

## Documentation

The backend's current [architecture guide](backend/ARCHITECTURE.md) describes
its API, service, integration, schema and repository packages. The refactor keeps
the existing HTTP contract, environment names and startup commands; legacy
Python imports remain compatible. See [validation](backend/REFACTOR_VALIDATION.md)
for the regression and integration evidence.

The [documentation-library index](SUBMISSION_README.md) describes the separate
PDF-only bundle: engineering history, database design, API reference,
implementation, setup, testing, operations and the illustrated manual.

The submission package includes a self-contained, 14-page
[technical documentation PDF](output/pdf/Resolve_Technical_Documentation.pdf)
and an [archive reading guide](SUBMISSION_README.md). These cover setup, architecture,
API/SDK integration, Postman tooling and the scope of recorded validation. The
source ZIP excludes the ignored `docs/` tree, so some historical links below refer
to material outside that package.

The [production-readiness assessment](docs/deployment/production-readiness-report.md)
and [testing report](docs/testing/testing-report.md) distinguish local evidence
from unverified hosted behavior. The [Render deployment guide](docs/deployment/deployment-guide.md)
accompanies `render.yaml`; deployment/account/billing and reviewed source publication
are still required. No production URL is claimed. The illustrated
[PDF user manual](docs/user-manual/user-manual.pdf),
[screenshot index](docs/user-manual/screenshots/README.md),
[video script](docs/presentation/video-script.md) and
[recording checklist](docs/presentation/recording-checklist.md) support demonstrations.
The [current Resolve film](video-production/README.md) is the **2:50 final
submission** in `Resolve_Final_Submission_Package/Resolve_Final_Submission.mp4`
(CHG-064). It adds actual Next.js dashboard coverage, complete paragraph-level
af_heart narration, stable footage, canonical subtitles and a no-music edition.
The native narration master and exact pitch-preserving 1.5× submission WAV are
included. It follows the actual USD 8 Sandbox purchase through complaint,
commitment, separate refund approval/execution and genuine Groq investigation.
PayPal uses REST alongside the first-party Resolve SDK; hosted deployment and
actual incoming webhook delivery remain unverified. The prior 4:30 master,
3:00 reference and 2:57 films remain intact in their original directories.
The [English narrated videos](docs/presentation/video/README.md) include a 7:32
project overview and a 24:31 detailed guide, using actual screenshots with
captions and chapters. [Open the local player](docs/presentation/video/watch.html)
after downloading the separately delivered MP4 files into that directory.
The [real integration report](docs/testing/production-integration-report.md) and
[SDK implementation guide](docs/user-manual/sdk-integration-guide.md) distinguish
the verified official Sandbox flow from unavailable providers and controlled tests.

Open `/docs` on the running website for ten guides covering first cases, merchant
and buyer workflows, returns, refunds/disputes, SDK/API integration, connections,
configuration and troubleshooting. The pages include local search, copyable
examples and printable articles. Download the complete guide and OpenAPI contract
from the documentation home. A repository copy is [Resolve guide](docs/RESOLVE_GUIDE.md).

## Integrate Resolve into your app

SDK 0.7 extends the order-page support flow: `openIssue` records the buyer's
problem once, `getOrderResolution` returns safe progress and the next action,
and `createSupportLink` opens the existing messages/offers/returns portal.
Owners enable this explicitly with an app-source support key. The
[embedded aftercare guide](docs/SDK_AFTERCARE.md) and
[checkout-store example](examples/checkout-store/README.md) show the complete path
from a damaged-item report to merchant handling, rather than just order sync.

The [aftercare reliability guide](docs/AFTERCARE_RELIABILITY.md) covers return
policy and inspection checks, reusable PDF labels, reason-specific dispute
checklists, capture-wide dispute holds, refund tracing and shared support context.
Apps can recover issue receipts after timeouts and reconcile missed updates with
a resumable event feed and transactional PostgreSQL consumer. Provider dispute
references and physical returns remain merchant-recorded; bank receipt is not
independently verified.

Merchant operations are available at `/account` and `/workspace/operations`:
individual staff roles, workspace onboarding, encrypted provider connections,
Zendesk conversation imports and signed webhook intake, daily overdue-promise
alerts, dashboard metrics, buyer offer acceptance, guided returns/replacements,
and reviewed dispute evidence exports. See the [setup and workflow guide](docs/PLATFORM_EXPANSION.md).
Automation needs the separate operations worker. Returns record merchant-arranged
fulfillment; packages do not submit disputes to PayPal. Provider account checks
and hosted deliveries still require merchant credentials and verification.

Resolution cases now automatically queue a private evidence investigation when
created or updated. A separate worker produces findings or a clear abstention;
merchants review them in the case workspace. Inference and automatic Sandbox
reads default to disabled. Investigation review never authorizes a refund.
See [automatic investigations, model policy and synthetic evaluation](docs/AI_INVESTIGATIONS.md).

Generate an SDK key in **Workspace → Settings → SDK keys** and copy the server
setup. Use the SDK’s `createResolve().syncOrder(order)` to publish an order.
To wire it up with an IDE assistant, use the
[Resolve SDK skill and copy-ready prompt](sdk/typescript/README.md#integrate-with-your-ide-assistant).

Use the [commerce integration](docs/COMMERCE_INTEGRATION.md) if your app already
takes PayPal payments. Sync a selected order, payment, and product snapshot
from your server using a direct API call or the SDK's read-only PostgreSQL
connector. Resolve compares it with PayPal Sandbox and flags missing or
mismatched records in the merchant's evidence bundle. The merchant **Orders**
view lists registered orders from connected apps, including orders without a
support case.

The [Resolve Evidence SDK](sdk/typescript/README.md) lets a merchant's Node.js
server open a case by its own reference, link PayPal records, and record events
such as a refund approval. Read what PayPal Sandbox confirmed, what is still
missing, and when Resolve last checked. The SDK also manages private buyer
status links. The quickstart includes local package installation and a runnable
example.
Other languages can use the [OpenAPI contract](postman/contracts/resolve.openapi.json).

## Development Documentation

- [Field Brew Supply: a six-product Sandbox store using the Resolve SDK](examples/checkout-store/README.md)

- [Build status and handoff: completed features, local setup, fixes, and remaining work](docs/BUILD_STATUS.md)

- [Merchant UI: run against your backend](frontend/README.md)
- [Customer portal: case links, access, and messaging](docs/CUSTOMER_PORTAL.md)
- [Buyer sign-in with Google and optional email delivery](docs/CUSTOMER_SIGN_IN.md)
- [Customer intake, evidence, and merchant triage](docs/CUSTOMER_WORKFLOW.md)
- [Hosted follow-up: email, My cases, automatic checks, and Zendesk](docs/HOSTED_FOLLOWUP.md)
- [PostgreSQL setup and SQLite import](docs/POSTGRES_MIGRATION.md)
- [Merchant sign-in, PayPal login, and hosted frontend setup](docs/MERCHANT_SIGN_IN.md)
- [Backend setup and API examples](backend/README.md)
- [Current status, sandbox result, and review steps](docs/PROJECT_STATUS.md)
- [Case workspace, commitment revisions, timeline, and recovery worker](docs/BACKEND_OPERATIONS.md)
- [Make a sandbox test purchase and verify its capture](docs/SANDBOX_TEST_PURCHASE.md)
- [Sandbox refund execution contract and recovery](docs/REFUND_EXECUTION.md)
- [PayPal HTTP simulation and its evidence limits](postman/README.md)
- [Engineering log: changes, decisions, reasons, tests, and limitations](docs/ENGINEERING_LOG.md)
- [Repository working instructions](AGENTS.md)

Every code change must include an engineering-log update in the same change set.
The log preserves the reasoning behind decisions as the implementation evolves.

## The Problem

When a purchase goes wrong, the information needed to resolve it is often scattered across:

- Customer-support conversations
- Order and return records
- Payment transactions
- Refund history
- Delivery evidence

A merchant may promise a refund without completing it. A refund may be partial, pending, or failed. Customers contact support repeatedly while teams reconstruct the same case.

Resolve aims to connect these records and track each commitment through to its outcome.

## How Resolve Works

1. **Capture the issue**
   Invite a customer to report an issue for their order, or create the case directly.

2. **Identify the commitment**
   Extract the proposed or agreed remedy, amount, conditions, deadline, and source message.

3. **Connect the records**
   Match the case to the correct order, PayPal payment, and relevant evidence.

4. **Reconcile the outcome**
   Compare the agreement with completed and pending refund activity.

5. **Coordinate the next action**
   Request missing information or present an appropriate action for merchant approval.

6. **Verify and communicate**
   Track the payment outcome and maintain a shared resolution history.

## Example

A merchant agrees to refund a $100 purchase after receiving the return.

The return arrives, but only a $20 refund has completed.

Resolve checks for additional pending or completed refunds, identifies any remaining commitment, and presents the merchant with the next appropriate action.

After authorization, the system requests the eligible refund and tracks its reported outcome.

The buyer receives a resolution record showing:

- The agreed remedy
- Completed payment actions
- Outstanding conditions or amounts
- The next action and its owner

## Implemented capabilities

### Commitment Tracking

- Extract refund commitments from support conversations.
- Preserve the original message and supporting evidence.
- Track conditions, deadlines, and revisions.
- Distinguish proposed remedies from accepted agreements.

### Payment Reconciliation

- Link commitments to PayPal payments.
- Track completed, partial, pending, and failed refunds.
- Identify incomplete outcomes.
- Calculate remaining amounts using deterministic backend logic.

### Resolution Coordination

- Request missing evidence.
- Present merchant-approved remedy options.
- Record buyer acceptance.
- Route exceptions to human review.

### Shared Resolution History

- Merchant case workspace
- Buyer status page
- Evidence timeline
- Action history
- Final resolution receipt

### Integrations and extension boundary

- Commerce and helpdesk integrations
- Return and replacement workflows
- Dispute evidence preparation
- Direct PayPal dispute submission remains future work; current packages are reviewed exports.

## AI and Backend Responsibilities

Optional advisory AI can interpret conversations, identify missing information, and explain recommendations. It defaults off and is subject to configured privacy and model policies.

Backend code will control:

- Payment and merchant identity checks
- Authorization
- Currency and amount validation
- Remaining refundable balance
- Pending refund checks
- Duplicate-action prevention
- Payment execution and status updates

An AI recommendation alone will not authorize a financial action.

## Implemented technology stack

| Layer | Technology |
| --- | --- |
| Frontend | Next.js, React, TypeScript |
| Styling | Local CSS tokens and responsive components |
| Backend | Python, FastAPI |
| Validation | Pydantic |
| Database | SQLite locally or PostgreSQL (Neon recommended for hosting) |
| Authentication | Merchant access keys or linked PayPal accounts; buyer email sign-in |
| Evidence storage | Case-scoped database attachments |
| AI integration | Optional Groq/OpenRouter adapters with validated structured outputs |
| Payment integration | PayPal REST APIs |
| Background processing | Python workers and database queues |
| Testing | pytest and Playwright |

The local frontend and backend run as separate processes.

Local configuration placeholders are in `backend/.env` and `frontend/.env.local`;
fresh checkouts can copy their respective `.env.example` files. Keep existing
values and fill only the integrations you intend to enable. AI configuration
uses a separate private `backend/.env.ai.ps1`: copy
`backend/ai-env.example.ps1`, fill it, and run `. .\.env.ai.ps1` from `backend`
before starting the API. See the [backend setup](backend/README.md#local-environment-files)
for activation and worker configuration.
OpenRouter investigations default to GPT-OSS 120B through Phala (currently
$0.60 per million output tokens), with free Xing4.0 optional. Requests cap output
token pricing at $0.74 per million. See the
[model choices and evidence limits](docs/AI_INVESTIGATIONS.md#model-decision-and-official-evidence).

SQLite is the credential-free default. FastAPI and both workers use PostgreSQL
when `RESOLVE_DATABASE_URL` is set. The [migration guide](docs/POSTGRES_MIGRATION.md)
shows how to verify a copy of the existing database before switching.

Merchant access supports individual email/password accounts and administrator-provisioned bearer tokens.
Create a merchant with `uv run python -m app.manage create-merchant --name "My store"`
from the backend directory, then use the returned token in the UI's Connect
account dialog or in Swagger. See the backend guide for key revocation and legacy-data assignment.
PayPal sign-in must be linked from an existing merchant workspace.
Owners manage staff invitations and owner/manager/finance/agent/viewer roles in Operations.

## Repository structure

```text
resolve/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── models.py
│   │   ├── storage.py
│   │   ├── postgres.py
│   │   └── *_routes.py / workflow services / provider adapters
│   ├── migrations/
│   └── tests/
├── frontend/
├── sdk/typescript/
├── examples/checkout-store/
├── postman/
├── docs/
├── render.yaml
└── README.md
```

See the [complete application inventory](docs/testing/application-inventory.md) for all routes, API operations, forms, roles, integrations and database operations.

## Development Roadmap

- [x] Initialize the repository
- [x] Create the FastAPI application and health endpoint
- [x] Define case, commitment, payment, and refund models
- [x] Add local database persistence and restart recovery tests
- [x] Add local merchant token authentication and case ownership checks
- [x] Add a PostgreSQL driver, schema and verified SQLite import
- [ ] Provision and verify a hosted PostgreSQL database
- [x] Implement reconciliation using sample records
- [x] Implement sandbox-only capture reads and local HTTP failure simulation
- [x] Verify OAuth authentication with the configured PayPal Sandbox app
- [x] Verify the client's capture read with the owner's PayPal Sandbox account
- [x] Save the actual sandbox capture through authenticated case endpoints
- [x] Implement approved PayPal Sandbox refunds and order-scoped history (account-wide completeness remains unverified)
- [x] Add persistent, state-bound merchant approvals and decision audit events
- [x] Add paginated case browsing, safe commitment revisions and a shared timeline
- [x] Add a local recovery worker for already-approved executions
- [x] Add durable first full-capture sandbox refunds and provider idempotency
- [x] Add partial and repeated refunds behind verified Sandbox order history
- [x] Add opt-in advisory AI commitment extraction and synthetic evaluation
- [x] Implement Sandbox webhook signature verification and event reconciliation
- [x] Add case attachments, close/reopen and the merchant review queue
- [x] Build the local merchant workspace and printable buyer receipt
- [x] Add local customer case links and two-way messaging
- [x] Add durable merchant browser login and optional PayPal identity
- [ ] Verify hosted buyer access and a registered PayPal OAuth callback
- [ ] Evaluate complete resolution workflows

## First Milestone

Complete one sandbox workflow:

```text
Payment
  → Customer complaint
  → Recorded refund commitment
  → Payment reconciliation
  → Merchant approval
  → Sandbox refund
  → Verified outcome
  → Resolution record
```

## Evaluation Plan

The initial evaluation will measure:

- Commitment-extraction accuracy
- Correct matching between cases and payments
- Detection of incomplete refund commitments
- Correct treatment of pending refunds
- Duplicate and excessive refund attempts blocked
- Recovery from interrupted payment requests
- Time to verified resolution

Any reported results will distinguish sample-data tests, sandbox behavior, and live merchant evidence.

## Project Scope

Resolve is an independent project designed to work with supported PayPal capabilities.

It assists merchants and buyers with resolution workflows. Formal dispute decisions remain with PayPal or the relevant financial institution.

Live merchant integrations will require the appropriate access, consent, and operational controls.
