# Resolve guide

SDK 0.7 · PayPal Sandbox

A practical guide for merchants, buyers and developers. All examples use placeholders or synthetic order data.

## Contents

- [Start your first resolution](#start-your-first-resolution)

- [Run the merchant workspace](#run-the-merchant-workspace)

- [Help a buyer without starting over](#help-a-buyer-without-starting-over)

- [Guide returns and replacements](#guide-returns-and-replacements)

- [Review refunds and disputes](#review-refunds-and-disputes)

- [Integrate the SDK](#integrate-the-sdk)

- [Use the API reliably](#use-the-api-reliably)

- [Connect supported services](#connect-supported-services)

- [Run and configure Resolve](#run-and-configure-resolve)

- [Troubleshoot common problems](#troubleshoot-common-problems)

## Start your first resolution

Learn the basics and try a merchant-to-buyer case without connecting a payment account.

### What Resolve does

Resolve is a payment aftercare platform. It brings a customer issue, merchant commitments, evidence, messages and resolution progress together. Merchants work in a workspace; buyers use a private case link or the support flow inside a connected store.

A request is what a customer asks for. A promise is what the merchant agrees to do. Evidence records what happened. A refund approval authorizes one reviewed action; submission and provider confirmation are separate steps.

> **Current scope**
> Payment verification and refund execution use PayPal Sandbox. SDK 0.7 is a local Node.js preview. Physical returns, tracing references and manually entered dispute updates retain their merchant-recorded source.

### Create a practice case

- [Create a workspace or sign in](/account)

1. Open /account and choose Create workspace. Enter your store name, name, email and a password of at least 12 characters. If you registered already, sign in.
2. Open Cases → New case. Enter “Customer received a damaged item” and optional order reference TEST-001.
3. Choose No linked payment, then Create case. This practice case needs no provider credentials.
4. Choose Add promise. Record the agreed remedy, its source, due date and any prerequisites.
5. Open Customer portal → Create customer link. Open the issued link in a private browser window to try the buyer view.
6. Send a message or upload sample evidence. Refresh the merchant conversation to see the update.

Already using a full merchant key? Sign in with that key at /login, then open /account?claim=1 to create the first individual owner for the same workspace. Creating a separate workspace gives it separate records.

### Choose your next step

A standalone case supports promises, messages, evidence and sharing. Item returns require a registered order with items. Refund reconciliation requires a linked payment and the relevant provider configuration.

- [Merchant workspace](#run-the-merchant-workspace)
- [Buyer portal](#help-a-buyer-without-starting-over)
- [SDK integration](#integrate-the-sdk)
- [Run Resolve locally](#run-and-configure-resolve)

## Run the merchant workspace

Handle cases, evidence, offers, overdue work and individual staff permissions.

### A practical daily workflow

1. Open Cases. Search by order or case reference and use workflow filters or At risk to find work needing attention.
2. Select a case. Read the next step, money summary, promises, due dates and evidence sources.
3. Record only the remedy actually agreed to, its source and prerequisites. Customer preferences remain separate until a merchant records a promise.
4. Use Customer portal to send a public update, collect evidence and create or revoke a private buyer link.
5. Open Operations → Missed promises → Scan workspace for overdue work and customer-update drafts. Review and send drafts through your chosen channel.
6. Use Manage case to close completed work. Case closure and verified payment completion remain separate facts.

### Read evidence by source

| Label | Meaning |
| --- | --- |
| Merchant recorded | A staff member or connected app recorded a fact or finding. |
| Provider confirmed | A supported provider returned evidence for this record; check timestamp and scope. |
| Needs review | Evidence is missing, conflicting, stale or awaiting a required decision. |
| Pending | An operation or prerequisite has not reached its final outcome. |

The timeline loads when opened. Secondary Zendesk, investigation, offer, return and dispute sections load on expansion. Refresh explicitly when you need newly arrived case data. AI suggestions and investigation reviews are advisory; they never authorize payment.

### Let a buyer accept an offer

1. Record current promise terms in the case.
2. Expand Buyer resolution offers. Choose up to four remedies and an expiry, then publish.
3. Share the current private buyer link. The buyer accepts one exact version or declines.
4. If terms change, publish current terms. Expired, replaced or stale offers cannot be accepted. Refunds still need separate approval and payment checks.

### People and permissions

| Role | Typical access |
| --- | --- |
| Owner | Workspace, team, connections, policies and financial work. |
| Manager | Case work and refund approval; no execution. |
| Finance | Refund approval and execution; owner-only configuration remains restricted. |
| Agent | Case handling, messages and ordinary evidence work; no financial approval or execution. |
| Viewer | Read-only access. |

Invite staff under Operations → Team and share the private invitation link. It expires after two days and is single-use; it is not emailed automatically. Role changes or disabling a member revoke their sessions. Policy exceptions and sensitive actions have additional role checks.

## Help a buyer without starting over

Use a private case to exchange messages, review offers, save labels and understand refund progress.

### Open the right case

Use the private link supplied by the merchant, or open support from your authenticated store order page. Keep the case link private. A replacement link invalidates the earlier case link. My cases can show cases tied to a verified email when optional sign-in is configured.

> **Customer ownership**
> A merchant app must authenticate its customer and verify order ownership before calling the SDK. Knowing an order number alone is not a sign-in method.

### Work through your resolution

1. Read the agreed remedy and next action. A requested refund or replacement may still need merchant agreement.
2. Reply in the existing conversation. Use Refresh messages to check for new replies.
3. Attach relevant receipts or photos. Case uploads support PDF, PNG and JPEG subject to the displayed size limit.
4. Review a current offer and accept the option you agree to. Remaining conditions still apply.
5. If returns are available, select actual order items and quantities, add a reason and request review.
6. Wait for approval and instructions. Save the uploaded PDF label so you can print it later, and keep your drop-off receipt.

### Understand refund progress

| Status or reference | What it establishes |
| --- | --- |
| Promised | An agreed commitment; no confirmed transfer yet. |
| Provider pending | The provider operation is still processing. |
| Sent to original payment method | Processor completion, without independent bank-receipt verification. |
| Needs verification or review | Evidence is unavailable, stale or conflicting. Unknown amounts are not zero. |
| ARN / STAN / RRN / bank reference | A merchant-supplied reference to help trace a recorded refund. |

If a store uses SDK receipt acknowledgement, it is buyer-reported and changes no payment ledger. Private merchant tracing notes are not shown. Ask for a new case link if yours expired or was revoked. Revoking a server SDK key does not itself revoke previously issued buyer links.

- [Returns and replacements](#guide-returns-and-replacements)
- [Troubleshooting](#troubleshoot-common-problems)

## Guide returns and replacements

Review real order items, disclose terms, save labels and record fulfillment milestones.

### Before requesting an item return

Register the order and item quantities through the SDK or commerce API and associate it with the case. A typed order reference does not create an item catalog. Existing non-rejected requests reserve quantities and reduce what remains available.

- [Register orders with the SDK](#integrate-the-sdk)

### Configure review rules

1. As an owner, open Operations → Connections → Return policy and review checks.
2. Enable the policy and set the delivery-based return window, shipping payer, disclosed fee, evidence requirements and inspection requirement.
3. Add products needing an exception and write default instructions, then save the current revision.
4. Review flagged dates, exclusions, missing evidence or repeated requests. Owners/managers can record documented policy exceptions where permitted.

> **Costs and eligibility**
> An inactive policy does not quote a free return. Confirm eligibility, shipping costs and fees before shipping. Flags are review prompts, not proof of fraud. No fee is charged automatically and quantity limits cannot be overridden.

### Give clear instructions and a reusable label

1. Open Guided returns and replacements in the case. Review the request and approve or decline it.
2. Expand Return instructions, saved labels and inspection. Save the address, instructions and shipping payer.
3. Upload an already arranged PDF return label, up to 2 MiB. Up to ten labels are stored per return; identical bytes reuse the existing label.
4. The buyer opens the same section in the private portal and chooses Save label PDF. They can print it later.

Resolve does not purchase postage or arrange carrier pickup. Actual shipment stays with the merchant and carrier.

### Keep milestones separate

| Stage | Record it when |
| --- | --- |
| Requested / approved | The buyer asks and the merchant reviews. |
| Return in transit | The merchant records the carrier, tracking and shipment reference. |
| Warehouse received | The warehouse confirms receipt; carrier delivery is a separate fact. |
| Inspection passed | A current item/quantity review satisfies active policy and return revisions. |
| Replacement shipped / complete | A replacement shipment or final workflow result is recorded. |

These are merchant-recorded findings. A dependent refund still needs its acceptance, condition, evidence and payment gates. Changed policy or return terms can make an earlier review stale.

## Review refunds and disputes

Understand balances, separate approvals, overlap holds and reason-specific evidence packages.

### Read the money summary

Link the correct payment record. Refund promises are cumulative commitments, not instructions to add the whole amount again on each attempt. Cases sharing a capture use one shared balance.

| Amount | How to read it |
| --- | --- |
| Promised | The current agreed cumulative amount. |
| Completed | Completed ledger observations; current independent provider evidence is shown separately. |
| Pending | Refunds still processing, kept separate from completed amounts. |
| Outstanding | What remains after applicable completed and pending amounts. |

The Operations dashboard labels recorded balances separately from provider proof. Unavailable provider history is not a verified zero.

### Follow the financial review flow

1. Check the linked capture, current PayPal history, prerequisites, conditions and any required buyer acceptance.
2. Refresh evidence where necessary. Missing/stale proof, conflicting history, disputes or uncertain previous submissions can block another action.
3. An owner, manager or finance user reviews an exact permitted amount and records a state-bound approval.
4. An owner or finance user submits the separately approved Sandbox refund when writes are explicitly enabled. Approval alone sends nothing.
5. Check execution and provider outcome. Reconcile an uncertain response using its original identity rather than issuing another refund.

> **Payment scope**
> This write path is PayPal Sandbox with explicit opt-ins. A support key, buyer acceptance or AI suggestion cannot execute a refund.

### Trace a recorded refund

An owner/finance user can add a provider-supplied ARN, STAN, RRN or bank reference for a refund already recorded on this capture. The buyer sees the labelled reference and stage; the private note stays private. Processor completion does not prove bank receipt, and Resolve does not fetch these references from a live bank.

### Hold overlapping remedies and prepare evidence

After linking the payment, an owner/manager/finance user can record reviewed dispute updates. API integrations retain stable event IDs and increasing versions. Older updates are ignored; conflicts are rejected. Active or reimbursed disputes hold the shared capture. A later manual close cannot erase reimbursement or override current provider-confirmed active dispute evidence.

Stripe and bank names here describe merchant-recorded references, not live connectors. A new hold cannot recall an already-sent payment request.

1. Classify owned delivery, product, policy, authorization, cancellation or credit evidence.
2. Open Dispute evidence packages and choose the actual reason. Prepare the immutable snapshot.
3. Inspect source labels and missing requirements. Replacement delivery is not original-delivery evidence.
4. An owner/manager reviews before export. Changed sources require a fresh package and review.

A checklist shows recorded support, not authenticity or a guaranteed outcome. Exporting does not submit anything to PayPal.

## Integrate the SDK

Put order support inside your store with scoped server keys and durable request IDs.

### Install the local preview

SDK 0.7 requires server-side Node.js 22.12 or newer. It is not published to npm. Pack the repository SDK, then install the archive in your merchant app.

```powershell
# From the Resolve repository
New-Item -ItemType Directory -Force .local/artifacts
Set-Location sdk/typescript
npm pack --pack-destination ../../.local/artifacts

# From your merchant app; replace the absolute path
npm install C:/path/to/resolve-paypal-sdk-0.7.0.tgz
```

### Create a support integration key

1. As an owner, open Operations → Connections → Customer support inside your store.
2. Choose a stable source such as my-store. Generate a support key and save the copied values on your app server.
3. Use the same source for order registration and support. Order-only keys do not automatically gain aftercare access.

```dotenv
RESOLVE_API_URL=http://127.0.0.1:3000/api/sdk
RESOLVE_API_KEY=<your-support-integration-key>
RESOLVE_APP_SOURCE=my-store
```

The website gateway exposes allowed commerce/aftercare actions. Full merchant helpers require direct FastAPI and full-key permissions. Never put a key in browser code or NEXT_PUBLIC variables.

### Register trusted order data

```typescript
import { createResolve } from "@resolve-paypal/sdk";
const resolve = createResolve();

// Read this from your app’s trusted order record.
await resolve.syncOrder({
  id: "ORDER-123", version: 1, status: "paid",
  items: [{ product_id: "CUP-01", name: "Ceramic cup",
    quantity: 1, unit_amount: "25.00" }],
});
```

Use a stable app order ID and increment version when its snapshot changes. Optional app payment references are merchant-reported until independently checked.

### Add the support flow

```typescript
// First authenticate the customer and verify ownership
// of this order in your own app database.
const orderId = "ORDER-123";
const requestId = savedComplaintUuid; // Persist once.
const receipt = await resolve.openIssue({
  orderId, requestId, reason: "damaged_item",
  message: "The cup handle arrived broken.",
  requestedResolution: "replacement",
});
const progress = await resolve.getOrderResolution(orderId);
const journey = await resolve.getRefundJourney(orderId);
const context = await resolve.getSupportContext(orderId);

// Only on an explicit action by the owning buyer:
const portal = await resolve.createSupportLink(orderId);
```

Status reads create no case and make no provider call. Opening an issue records a customer request, not an approved promise. Creating a support link replaces the previous case link, so do not rotate it while polling.

### Other useful methods

| Method | Purpose |
| --- | --- |
| lookupIssue | Recover a receipt using the original order/request UUID. |
| getReturnEligibility | Check items, flags and disclosed terms. |
| requestOrderReturn / getOrderReturns | Submit a stable request or read its workflow. |
| getReturnGuide / downloadReturnLabel | Show instructions and save a merchant-supplied PDF. |
| pullEvents / PostgresResolutionConsumer | Reconcile missed state into your app database. |

- [API reliability](#use-the-api-reliably)
- [Download OpenAPI](../postman/contracts/resolve.openapi.json)

## Use the API reliably

Choose the right authentication boundary and recover from duplicates, missed updates and timeouts.

### Authentication and API families

| Boundary | Purpose |
| --- | --- |
| Full merchant key / staff session | Merchant actions with ownership and role checks. |
| Support integration key | Source-granted commerce/aftercare calls from the app server. |
| Buyer capability | Only the case covered by the current private link. |

Direct API calls use Authorization: Bearer. Website merchant sessions use HttpOnly cookies. Your app must still verify which buyer owns an order.

| Path | Purpose |
| --- | --- |
| /resolution-cases | Promises, evidence and timelines. |
| /platform | Accounts, team, connections, offers, returns and packages. |
| /commerce/orders | Register and compare app orders. |
| /aftercare | Issues, status, context, return guidance and event pulls. |
| /cases/{id}/refund-approvals and /refund-executions | Separate financial review and submission. |

Interactive local API documentation is at http://127.0.0.1:8000/docs. Use your configured backend address when hosted. The downloaded contract has exact methods, schemas and validation rules.

- [Download OpenAPI](../postman/contracts/resolve.openapi.json)

### Keep identity after an uncertain response

A timeout does not establish whether a request committed. Persist one UUID before sending and retain the original intent on retries. lookupIssue retrieves its receipt; reusing an ID with changed content conflicts.

Retry-safe SDK actions get up to three attempts by default within the deadline. Authentication, validation, conflicts, cancellation and long rate limits return to the caller. Portal rotation, merchant mutations and financial actions are not automatically retried. Reconcile an unknown refund rather than issuing another one.

### Recover missed state

pullEvents reads a source-scoped state journal with a cursor and increasing order revisions. Pulls reconcile bounded connected orders; the operations worker also refreshes projections. Poll on a schedule for larger workspaces. This is a pull stream, not an outbound webhook subscription, and it recovers current state rather than every transient transition.

### Commit the app update and cursor together

```typescript
import { PostgresResolutionConsumer } from "@resolve-paypal/sdk";
const page = await resolve.pullEvents();
const consumer = new PostgresResolutionConsumer(pool, {
  merchantId: page.merchant_id, source: page.source,
  consumerId: "order-support",
});
await consumer.initialize();
await consumer.poll(resolve, async (event, transaction) => {
  const resolution = event.snapshot.resolution;
  if (!resolution || typeof resolution !== "object" ||
      !("stage" in resolution) ||
      typeof resolution.stage !== "string") {
    throw new Error("Missing resolution state");
  }
  await transaction.query(
    "UPDATE my_orders SET support_stage=$1 WHERE order_id=$2",
    [resolution.stage, event.order_reference],
  );
});
```

Supply your writable PostgreSQL pool and adapt the example’s app table and columns. Explicit initialization creates two SDK tables. Keep a stable consumer ID and use the supplied transaction: errors roll back app writes and cursor together. Enqueue remote notifications in your own transactional outbox; external effects still need independent idempotency.

## Connect supported services

Configure the owning workspace’s providers and understand their current scope.

### Save and check a connection

1. As an owner, open Operations → Connections.
2. Enable the provider and enter its required configuration and secrets. Blank secret fields retain existing secrets.
3. Save and choose Check connection. Returned status is redacted.
4. Verify an actual owned record separately. Working credentials do not prove capture ownership or payment outcome.

Saved workspace credentials need a stable RESOLVE_PLATFORM_ENCRYPTION_KEY in the backend and workers. Back it up privately; replacing it can make saved secrets unreadable.

### Supported scope

| Service | What it does |
| --- | --- |
| PayPal | Sandbox payment/refund evidence and separately gated Sandbox refunds; optional merchant sign-in. |
| Zendesk | Ticket imports and signed webhook intake; uncertain order matches require confirmation. |
| Shopify / EasyPost | Optional read-only order/return/tracking evidence; postage and fulfillment remain external. |
| SMTP / Resend | Optional customer mail through the follow-up worker. |
| Google | Optional buyer sign-in for My cases. |
| Groq / OpenRouter | Optional advisory suggestions/explanations/investigations under configured policy. |

Stripe/bank references are manual records, not live connectors. Hosted OAuth and callbacks require account-backed configuration.

### Preserve support context

Enter a Zendesk ticket number under Support imports. Unique exact order matches may link a case; otherwise select and confirm a match. Source IDs and public/private labels are retained. Private imported comments are not copied into buyer conversations.

For automation, configure the displayed workspace webhook URL and matching signing secret, then run the operations worker. Hosted providers need a reachable HTTPS URL; localhost alone cannot receive callbacks.

### Set a customer-visible sender

```dotenv
RESOLVE_CUSTOMER_EMAIL_ENABLED=false
RESOLVE_CUSTOMER_EMAIL_TRANSPORT=smtp
RESOLVE_SMTP_HOST=<hostname-from-your-email-provider>
RESOLVE_SMTP_PORT=587
RESOLVE_SMTP_SECURE=false
RESOLVE_SMTP_USER=<your-smtp-login>
RESOLVE_SMTP_PASSWORD=<your-smtp-credential>
RESOLVE_SMTP_FROM=Resolve Support <support@example.com>
```

Use a sender your provider authorizes. SMTP_USER is the login; SMTP_FROM is the visible sender. Follow your provider’s port/TLS requirements. Enable delivery after configuring mail and the required merchant binding. Saving settings does not send mail; the follow-up worker performs delivery.

## Run and configure Resolve

Start a responsive local preview and keep settings and workers in the correct environment.

### Prerequisites

- Python 3.12 or newer and uv.
- Node.js 22.12 or newer for the SDK, which also satisfies the frontend requirement.
- SQLite for a local start, or explicitly configured PostgreSQL.
- Provider credentials only for integrations you enable.

Use ignored local files or a deployment secret store. Examples contain placeholders. Preserve your existing database settings when preparing a separate test environment.

### Start the API and optimized website

```powershell
# Terminal 1, from the repository root
Set-Location backend
uv sync
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000

# Terminal 2, from the repository root
npm --prefix frontend ci
npm --prefix frontend run build:preview
npm --prefix frontend run preview
```

Open http://127.0.0.1:3000/account and keep both processes running. Stop another frontend on port 3000 first. The compiled preview uses .next-preview; rebuild and restart after source/configuration changes. Use npm --prefix frontend run dev for automatic reload while editing, instead of the compiled preview.

### Configuration locations

| Location | Purpose |
| --- | --- |
| backend/.env | Database, ordinary providers, email, origins and switches. See backend/.env.example. |
| frontend/.env.local | Backend URL and website origins. See frontend/.env.example. |
| Private PowerShell AI environment | Copy backend/ai-env.example.ps1 and explicitly load the private copy into API/worker processes. |
| Merchant app server | RESOLVE_API_URL, RESOLVE_API_KEY and RESOLVE_APP_SOURCE. |

AI settings use process variables rather than ordinary dotenv loading. Enable only configured features. Keep browser origins consistent and hosted callbacks on HTTPS.

### Run only the workers you need

| Command from backend | Work |
| --- | --- |
| uv run python -m app.operations_worker --loop | Imports, overdue scans and projections; no mail or financial submission. |
| uv run python -m app.investigation_worker --loop | Automatic evidence investigations under configured policy. |
| uv run python -m app.followup_worker --loop | Customer follow-up jobs and optional email delivery. |
| uv run python -m app.worker --loop | Configured refund recovery/reconciliation; review its CLI/payment settings first. |

Workers need the correct database, encryption key and environment. The website does not start them. Use --help for interval/limit controls. Keep numbered migrations immutable and test schema changes against disposable storage. Hosted operation also needs stable origins, backups, secret management and account-backed checks.

## Troubleshoot common problems

Find a useful next check for login, returns, refunds, background jobs and preview updates.

### Login and support access

| Symptom | Next check |
| --- | --- |
| Cannot sign in | Use an individual account or full merchant key. Commerce/support keys cannot sign in. |
| Empty workspace | Check the merchant account; newly created workspaces have separate records. |
| SDK 403 | Verify app source and explicit support grant; order-only keys cannot use aftercare. |
| Invalid buyer link | Ask for a current link; expired, replaced and revoked links cannot be reused. |

### Orders, returns and evidence

| Symptom | Next check |
| --- | --- |
| No return items | Register owned items, connect the order to the case and check existing reservations. |
| Stale return review | Reload current policy/return versions and record a current review or permitted exception. |
| No saved label | The merchant must arrange and upload a PDF; postage is external. |
| Stale evidence export | Build a fresh package, inspect sources and review before export. |

### Refund progress and timeouts

| Symptom | Next check |
| --- | --- |
| Unknown amounts | Refresh evidence; unavailable/stale proof is not zero. |
| Approval blocked | Read acceptance/conditions, provider history, balance, pending refunds, disputes and uncertain executions. |
| Processor complete, bank money missing | Check provider proof and any merchant tracing reference. Bank receipt is not independently verified. |
| Network timeout | Retain the original UUID and recover/reconcile that request instead of creating another refund. |

### Workers and AI

| Symptom | Next check |
| --- | --- |
| Imports or alerts not updating | Check the operations worker, connection status and owning database/key. |
| Investigation queued | Run its worker and inspect status. Missing advice does not authorize anything. |
| No email | Check enabled transport, sender, merchant binding, queue and follow-up worker. |
| AI fallback | Check process credentials, switches, policy, routes and budgets; abstention can be valid. |

### Website updates

1. Use the compiled preview for normal viewing; a development route may compile before loading.
2. After a frontend edit or merge, rebuild with npm --prefix frontend run build:preview and restart npm --prefix frontend run preview.
3. Refresh with Ctrl + Shift + R for new assets, and refresh messages/details for newly arrived data.
4. Check http://127.0.0.1:8000/health and RESOLVE_BACKEND_URL if the API is unreachable. Hosted database network latency still affects reads.

- [Run Resolve](#run-and-configure-resolve)
- [API reliability](#use-the-api-reliably)
