# Resolve - build status and handoff

This is the 7 November snapshot. For subsequent investigations and the eight
merchant operations additions, see [AI investigations](AI_INVESTIGATIONS.md),
[merchant operations](PLATFORM_EXPANSION.md) and CHG-048 in the engineering log.

**Reviewed:** 7 November 2026 (Asia/Calcutta) · **Code snapshot:** Evidence SDK baseline `9eaa616` plus commerce and merchant orders and SDK key setup (CHG-029–032) · **SDK:** `@resolve-paypal/sdk@0.5.0`

Resolve connects a buyer's issue, the merchant's promise, and the records that
show whether that promise was kept. It supports merchants, buyers, and
developers integrating from their own servers. The current build is a working
local MVP with PayPal Sandbox support. The remaining work is primarily hosted
setup and real-account verification. Live money movement and AI are outside the
current scope.

- **Complete** means built and verified within the stated scope.
- **Built; setup or verification pending** means the code exists, but a hosted
  flow or genuine provider account has not been proven.
- **Not built** means a new feature or expansion is required.

## What is complete

| Area | Built and usable today | Boundary |
| --- | --- | --- |
| **Public site and demo** | Landing page, separate demo workspace, merchant login, and separate buyer entry. The demo covers case review, refund approval, and an outside refund before submission. | Demo records are synthetic and resettable; the demo does not call PayPal. |
| **Merchant access and inbox** | Provisioned, hashed, revocable access keys; browser sessions and sign-out; merchant-scoped case search; unread messages, assignment labels, due dates, and filters including waiting on customer, needs approval, and pending with PayPal. | Assignment is a shared label. Individual staff accounts and roles are not built. |
| **Case lifecycle and evidence** | Open cases with or without payments, link an existing owned payment, keep versioned promises and evidence, attach files, and use the refund case's close/reopen and exception review flows. Merchants can inspect timelines, export a private evidence bundle, and print a buyer receipt. | Case closure, promise fulfillment, and payment outcomes are separate. Untimestamped legacy events are not fabricated. |
| **Buyer intake and evidence** | Order-specific invite creates one case, reuses it on retry, and can collect issues such as a missing item, duplicate charge, damage, or delayed refund. Buyers can upload PDF, PNG, or JPEG evidence; merchants see it labeled customer submitted. | An order number cannot grant access. Buyer files are capped at 2 MiB each and 10 per case. A file is evidence submitted by the buyer, not provider confirmation. |
| **Buyer portal** | Expiring, replaceable, revocable private case link; buyer-facing milestone timeline, next actor, due/overdue state, and two-way conversation. An order reference is shown only if permitted. | A private link does not require a buyer account. Merchant notes, provider identifiers, and the private evidence bundle stay in the workspace. Local links need a public frontend origin before remote sharing. |
| **PayPal payment and refund workflow** | Seller-scoped Sandbox capture verification; manual refund observations separated from provider evidence; completed/pending/failed refund states; exact remaining amounts; separately approved refund submission and recovery of uncertain outcomes. One real **USD 1.00 full Sandbox refund** was independently confirmed and reconciled to zero remaining. | The supported history path covers one USD capture per order. A real partial or repeated refund has not been proven. Refund writes are off by default in the code and require opt-in and exact approval. |
| **Multi-remedy case workspace** | Several promises in one case, with revision history, due dates, dependencies, and source evidence. A refund can wait for an explicitly confirmed prerequisite such as warehouse receipt. | Other remedies are tracked or verified by reads. The only provider write in the app is a separately approved PayPal Sandbox refund. |
| **Persistence and operations** | FastAPI/Pydantic, SQLite by default, PostgreSQL support via `RESOLVE_DATABASE_URL`, merchant CLI, recovery and follow-up workers, and an importer from SQLite to an empty PostgreSQL schema. Current migrations: SQLite `020`, PostgreSQL `009`. | Import, upgrades, and concurrency were exercised on disposable databases. The production deployment and both workers still need a smoke test with the intended database. |
| **Evidence SDK v0.5.0** | Server-side Node.js/TypeScript client: `upsertCase`, `linkRecord`, `addEvidence`, `refreshEvidence`, `getCase`, `getTimeline`, `getEvidenceBundle`, and `createBuyerLink`. Stable references/events support safe retries; conflicts return `409`. PayPal checks report gaps and preserve prior verified results on failure. Types are generated from FastAPI OpenAPI. | Local npm archive, not an npm registry release. The SDK is read-only toward PayPal; an SDK approval event does not grant refund authorization. Non-PayPal SDK references are recorded associations. |
| **Commerce integration** | The SDK reads one order from app-owned PostgreSQL views, or any backend pushes an allowlisted snapshot. Resolve reuses the case and reports field-level app vs PayPal differences. Optional contact fields are separated and require full merchant access to read. | Working against a real disposable app database and simulated PayPal. Real account configuration and Sandbox visibility still need a deployment check. The SDK does not read passwords or pull arbitrary tables. |
| **Merchant order dashboard** | Browse and search app orders, view line items and PayPal references, and open a resolution case on demand. The SDK can register individual orders or backfill from merchant-owned PostgreSQL views. | Visibility is limited to orders the app registered to that merchant workspace. The isolated store demo is separate. |

### Remedies the workspace can track

The workspace's provider adapters and the Evidence SDK have different scopes.
The SDK verifies supported PayPal Sandbox order, capture, and refund records.
The workspace also supports the following remedy checks when configured:

| Remedy | What Resolve can record or verify | Still outside the current feature |
| --- | --- | --- |
| Full, partial, or multiple refunds | Agreed amount, pending/completed amounts, fresh order-scoped history, and exact separately approved Sandbox actions. | Merchant-wide history, unsupported order shapes, and account-backed partial/multiple verification. |
| Return or conditional refund | Carrier delivery via EasyPost; explicit merchant findings for warehouse receipt or inspection; prerequisite gating. | Carrier delivery does not establish warehouse receipt or authorize an automatic refund. |
| Replacement or reshipment | Replacement reference and matched tracking; label, movement, and delivery are distinct. | Creating a shipment or buying a label. |
| Order cancellation or release of a hold | Shopify cancellation and/or PayPal voided authorization. A captured payment follows a separate refund promise. | Cancelling an order or voiding an authorization from Resolve. |
| Subscription pause or cancellation | Read the expected PayPal subscription status. | Changing the subscription or automatically refunding the previous bill. |
| Store credit or exchange | Read the exact Shopify credit issuance or matching exchange fulfillment. | Issuing credit, calculating spendable balance, or fulfilling an exchange. |
| Billing correction | Read invoice cancellation, or match payment evidence to a separately verified corrective refund. | Automatically deciding that two charges are duplicates or modifying an invoice. |
| Formal dispute handoff | Read PayPal dispute status and seller deadline when supplied; prepare a private evidence bundle for review. | Submitting a response, appealing, or treating the Resolve case as the formal dispute. |

## Built, but needs setup or real-account verification

This snapshot checks the ignored local environment files for presence, enabled
flags, and origin agreement. It does not disclose values or prove that a
credential works. Hosted environment values may be different.

| Integration | What is configured locally | What is left |
| --- | --- | --- |
| **PostgreSQL** | `RESOLVE_DATABASE_URL` is present; local API health returned `200`. | On the target deploy, confirm TLS connectivity, schema `009`, restart, and access to the same database from both workers. Health alone does not prove those checks. |
| **PayPal Sandbox reads and writes** | Read credentials and merchant binding fields are present. Reads, writes, and partial-refund flags are enabled in the local file. | Keep both write flags off in general demos and hosted environments unless intentionally running an approved Sandbox write. Verify a separate external partial refund and its totals; do not reuse the fully refunded USD 1.00 capture. |
| **Log in with PayPal (merchant)** | Enabled; login credentials are present. Backend and frontend merchant origins match on loopback. A real Sandbox account link was previously observed. | Verify the full sign-out and fresh **Log in with PayPal** flow, then repeat with the exact hosted HTTPS callback. Payment API permissions and PayPal identity are separate. |
| **PayPal webhook and recovery** | Signature verification, deduplication, inbox processing, and recovery are implemented and simulated. Webhook registration ID is unset locally. | Register the public HTTPS `/webhooks/paypal/sandbox` endpoint on the matching Sandbox app, set the webhook ID, start the recovery worker, and confirm a real signed supported event is reconciled. |
| **Resend email and email My cases** | Resend is selected, its required fields are populated, and email sending is **disabled**. The backend buyer origin is loopback; the frontend buyer origin is unset. | Verify the sending domain and address, set the same public HTTPS buyer origin on both apps, enable email in the intended environment, and start the follow-up worker. Test invite delivery, a one-time login link, a merchant reply, and a supported refund notice. Provider acceptance and inbox delivery are separate. |
| **Google My cases (buyer)** | Flow and mailbox matching are implemented and simulated. Google client credentials and enable flag are unset locally. | Configure the Google web OAuth client and exact `/api/customer-account/google/callback`. Test with a verified address already assigned to a buyer case. Private links work without Google. |
| **Nodemailer SMTP** | Optional transport is built and tested over local TLS. Resend is selected for this project. | No work required for a Resend deployment. A real SMTP relay is unverified if this alternative is chosen later. |
| **Shopify, EasyPost, and Zendesk** | Read connectors exist. No local account credentials are configured; automatic provider refresh is off by default. | Connect only the services needed for the demo. Verify a real read for each enabled account. The existing worker can poll eligible Shopify/EasyPost promises; native Shopify/carrier webhooks and Zendesk ticket sync are not built. |
| **SDK distribution** | Package built and installed from the local archive; the ORDER-1042 example ran through the actual API using simulated PayPal. | Verify the SDK refresh on a genuine Sandbox partial-refund record. Publish to a registry only if public install is needed. |

## Fixes already shipped and next actions

**Already fixed:** PostgreSQL startup errors at versions `003` and `005` were
handled by restoring the original migrations and adding forward migrations
`004` and `006`. Do not edit applied SQL, change stored checksums, or reset the
database to work around a mismatch. The migration guide covers what to inspect
if a different release still fails startup.

| Priority | Next action | Done when |
| --- | --- | --- |
| **P0 · Before sharing access** | Replace any Resolve merchant key previously pasted in chat if it is still active. Issue a new key, update the server-side consumer, then revoke the old key. Check deployed flags so Sandbox writes are enabled only where intentional. | The new key works, the old key fails, and non-payment demos can run with writes disabled. |
| **P0 · Main evidence demo** | Use a new Sandbox purchase. Record an approval in Resolve, issue the partial refund outside Resolve in Sandbox, then run a read-only SDK refresh. Check both capture-only discovery and explicit order linking. | The app shows missing confirmation before the refund, then the correct refund ID, amount, status, and check time. Repeated refreshes do not duplicate evidence. |
| **P0 · Hosted baseline** | Deploy the frontend and FastAPI, set the backend URL and exact public origins, and verify PostgreSQL migration and worker access. Keep private API routes behind the intended server integration or authenticated access. | Hosted pages load over HTTPS; merchant sign-in and a private buyer link work in separate sessions; a test case survives restart. |
| **P1 · Provider and buyer integrations** | Verify one genuine PayPal webhook and the hosted PayPal login flow; turn on Resend after verifying sender and origin. Add Google only if the demo needs My cases without email links. | The real webhook is verified and processed, merchant PayPal sign-in opens only its linked workspace, and a buyer can receive and redeem a one-time link for their assigned case. |
| **P2 · Optional expansion** | Validate Shopify/EasyPost/Zendesk against real test accounts and choose one convincing non-refund demo, such as a tracked replacement or a return-gated refund. | The case shows why a carrier milestone differs from a warehouse milestone, or why a label alone does not count as shipment. |

**Not built:** AI extraction or recommendations; production PayPal payments or
refunds; automated seller onboarding for arbitrary merchants; merchant-wide or
cross-app PayPal history; team roles; provider-side actions for non-refund
remedies; two-way helpdesk sync. Before production use, also plan monitoring,
backup/restore, retention, and storage and worker load tests. Those are
production readiness tasks, not prerequisites for the local demo.

## Verification record

| Evidence level | Result |
| --- | --- |
| **Local smoke check for this handoff** | `/health`, buyer capability endpoint, and frontend `/`, `/login`, `/demo`, and `/customer` all returned HTTP `200`. These are availability checks, not authenticated or hosted flow tests. |
| **Latest SDK milestone** | **252** backend tests passed; **59** opt-in tests skipped. **15** targeted isolated PostgreSQL tests passed. **4** Node SDK tests passed with **25** mocked requests and zero pass-through. The archive installed and its public types compiled in a fresh Node project. |
| **PayPal regression simulation** | **40** tests passed with **277** mocked requests and zero pass-through in the SDK milestone. ORDER-1042 separately confirmed the USD 25 partial refund, retry deduplication, tenant isolation, buyer privacy, and prior proof retained after a provider outage. No financial POST in the SDK flow. |
| **Earlier UI and integration milestones** | Frontend type check and production build passed; **14** core Playwright tests and a separate simulated Google buyer browser test passed. Resend, webhook protocol, and external remedy adapters have local simulation coverage. |
| **Account-backed PayPal Sandbox** | A previous authenticated capture check and one **USD 1.00 full refund** were independently verified. The order-scoped reader also discovered that existing refund. No account-backed partial-refund or signed webhook evidence is recorded. |

## Run it and find the details

From the repository root, use separate terminals for the API and UI. Skip the
install commands when dependencies are already installed:

```powershell
uv --directory backend sync
uv --directory backend run uvicorn app.main:app --reload
```

```powershell
npm --prefix frontend ci
npm --prefix frontend run dev
```

- **Try it:** [landing page](http://127.0.0.1:3000/),
  [demo](http://127.0.0.1:3000/demo),
  [merchant login](http://127.0.0.1:3000/login), and
  [local API docs](http://127.0.0.1:8000/docs).
- **Buyer and merchant flow:** [intake and triage](CUSTOMER_WORKFLOW.md),
  [buyer portal](CUSTOMER_PORTAL.md), and [merchant sign-in](MERCHANT_SIGN_IN.md).
- **Providers and operations:** [refunds and webhooks](PAYPAL_RECONCILIATION.md),
  [multi-remedy workspace](RESOLUTION_WORKSPACE.md),
  [buyer sign-in and email](CUSTOMER_SIGN_IN.md),
  [workers and hosted follow-up](HOSTED_FOLLOWUP.md), and
  [PostgreSQL and migration repairs](POSTGRES_MIGRATION.md).
- **Developer integration:** [Commerce integration](COMMERCE_INTEGRATION.md), [SDK quickstart and runnable example](../sdk/typescript/README.md),
  [OpenAPI](../postman/contracts/resolve.openapi.json), and
  [local simulation commands](../postman/README.md).
- **Evidence behind the status:** [engineering log](ENGINEERING_LOG.md) and
  [account-backed demo and historical verification](PROJECT_STATUS.md).
