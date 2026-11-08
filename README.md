# Resolve for PayPal

### From refund promise to verified resolution.

Resolve is a payment aftercare platform for PayPal merchants. It connects customer-support commitments with payment records, identifies incomplete refunds, and helps merchants coordinate authorized remedies.

A successful payment does not always mean a successful purchase. Resolve helps buyers and merchants understand what was agreed, what has happened, and what still needs to be done.

> **Status:** The public landing page links to a sample demo, private buyer portal, and authenticated merchant workspace. PayPal sign-in for merchants and Google or email sign-in for buyers are optional. Email notices, automatic provider checks, and Zendesk linking are optional. Hosted OAuth and payment webhook delivery still need account-backed verification. PayPal Sandbox refund writes default to disabled.

The [resolution workspace](docs/RESOLUTION_WORKSPACE.md) can track several
promises in one case: refunds, returns, replacements, cancellation, subscriptions,
store credit/exchanges, billing corrections, and dispute handoff. PayPal, Shopify,
and EasyPost evidence reads are optional; refund execution remains the only
provider write.

## Integrate Resolve into your app

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

- [Merchant UI: run the demo or connect your local backend](frontend/README.md)
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

## Planned Features

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

### Future Extensions

- Commerce and helpdesk integrations
- Return and replacement workflows
- Dispute evidence preparation
- Supported PayPal Disputes API workflows

## AI and Backend Responsibilities

AI will help interpret conversations, identify missing information, and explain recommendations.

Backend code will control:

- Payment and merchant identity checks
- Authorization
- Currency and amount validation
- Remaining refundable balance
- Pending refund checks
- Duplicate-action prevention
- Payment execution and status updates

An AI recommendation alone will not authorize a financial action.

## Planned Technology Stack

| Layer | Technology |
| --- | --- |
| Frontend | Next.js, React, TypeScript |
| Styling | Local CSS tokens and responsive components |
| Backend | Python, FastAPI |
| Validation | Pydantic |
| Database | SQLite locally or PostgreSQL (Neon recommended for hosting) |
| Authentication | Merchant access keys or linked PayPal accounts; buyer email sign-in |
| Evidence storage | Case-scoped database attachments |
| AI integration | OpenAI API with structured outputs |
| Payment integration | PayPal REST APIs |
| Background processing | Python workers and database queues |
| Testing | pytest and Playwright |

The local frontend and backend run as separate processes.

SQLite is the credential-free default. FastAPI and both workers use PostgreSQL
when `RESOLVE_DATABASE_URL` is set. The [migration guide](docs/POSTGRES_MIGRATION.md)
shows how to verify a copy of the existing database before switching.

Local merchant access currently uses administrator-provisioned bearer tokens.
Create a merchant with `uv run python -m app.manage create-merchant --name "My store"`
from the backend directory, then use the returned token in the UI's Connect
account dialog or in Swagger. See the backend guide for key revocation and legacy-data assignment.
PayPal sign-in must be linked from an existing merchant workspace.
Team roles remain separate work.

## Proposed Repository Structure

```text
resolve/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── api/
│   │   ├── models/
│   │   ├── services/
│   │   └── integrations/
│   └── tests/
├── frontend/
├── docs/
└── README.md
```

This structure is a development plan and will evolve with the implementation.

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
- [ ] Integrate approved PayPal Sandbox refunds and complete refund history
- [x] Add persistent, state-bound merchant approvals and decision audit events
- [x] Add paginated case browsing, safe commitment revisions and a shared timeline
- [x] Add a local recovery worker for already-approved executions
- [x] Add durable first full-capture sandbox refunds and provider idempotency
- [x] Add partial and repeated refunds behind verified Sandbox order history
- [ ] Add AI commitment extraction
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
