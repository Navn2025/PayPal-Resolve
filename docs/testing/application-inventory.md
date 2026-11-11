# Application inventory

Inspected 2026-11-11. Generated from source and the checked-in OpenAPI contract; inventory is not proof of runtime behavior.

## Structure and technology

- `frontend/`: Next.js 16 App Router, React 19, TypeScript, local CSS and Lucide icons. Server-side API gateways keep merchant credentials out of client code.
- `backend/app/`: FastAPI/Pydantic, synchronous storage services, HTTPX provider adapters, four independent worker entry points.
- `backend/migrations/`: 28 numbered SQLite migrations; `postgres/`: 19 numbered PostgreSQL migrations. Initialization applies checksum-tracked migrations; never edit an existing migration.
- `sdk/typescript/`: server-only Node SDK 0.7, generated OpenAPI types, commerce views/consumers. `examples/checkout-store/`: separate illustrative store, outside the Resolve navigation.
- `postman/`: provider contracts, loopback HTTP mocks and simulations. `docs/`: engineering decisions and feature guides. `.local/`: ignored disposable evidence/runtime files.
- Files/evidence and saved labels are database-backed. No object-storage service is implemented. Provider secrets use Fernet encryption; session/key values are hashed at rest.

## All application page routes

| Route | Source | Access / purpose |
|---|---|---|
| `/account` | `frontend/app/account/page.tsx` | Staff login, workspace signup, owner claim (?claim=1), invitation acceptance (#token) |
| `/customer/account` | `frontend/app/customer/account/page.tsx` | Buyer My cases; optional email link and Google sign-in |
| `/customer` | `frontend/app/customer/page.tsx` | Private-link entry, intake, messages, offers, returns; no sample mode |
| `/demo` | `frontend/app/demo/page.tsx` | Retired route: redirects to /login |
| `/docs/[slug]` | `frontend/app/docs/[slug]/page.tsx` | Ten public static guide articles, anchors, copy and print |
| `/docs` | `frontend/app/docs/page.tsx` | Public searchable guide hub |
| `/login` | `frontend/app/login/page.tsx` | Merchant access-key / optional linked PayPal sign-in |
| `/` | `frontend/app/page.tsx` | Public landing |
| `/workspace/operations` | `frontend/app/workspace/operations/page.tsx` | Authenticated overview, missed promises, team, connections, imports and audit |
| `/workspace/orders` | `frontend/app/workspace/orders/page.tsx` | Authenticated registered orders, search and open/create case |
| `/workspace` | `frontend/app/workspace/page.tsx` | Authenticated case inbox; ?case=UUID opens nested case details |
| `/workspace/settings` | `frontend/app/workspace/settings/page.tsx` | Authenticated account, PayPal identity linking and scoped SDK keys |
| `/docs/getting-started` | `frontend/content/docs.json` | Start your first resolution |
| `/docs/merchant-workspace` | `frontend/content/docs.json` | Run the merchant workspace |
| `/docs/buyer-portal` | `frontend/content/docs.json` | Help a buyer without starting over |
| `/docs/returns-and-replacements` | `frontend/content/docs.json` | Guide returns and replacements |
| `/docs/refunds-and-disputes` | `frontend/content/docs.json` | Review refunds and disputes |
| `/docs/sdk-integration` | `frontend/content/docs.json` | Integrate the SDK |
| `/docs/api-and-reliability` | `frontend/content/docs.json` | Use the API reliably |
| `/docs/connections` | `frontend/content/docs.json` | Connect supported services |
| `/docs/running-resolve` | `frontend/content/docs.json` | Run and configure Resolve |
| `/docs/troubleshooting` | `frontend/content/docs.json` | Troubleshoot common problems |

Unknown routes use `app/not-found.tsx`. The API documentation `/docs` on the backend is FastAPI Swagger, distinct from frontend user guides.

## Navigation and interactive modes

Case details: Overview, Evidence timeline, Resolution receipt, Customer portal. Inbox includes search, lifecycle/workflow/review/risk filters, new case, invitation and review queue. Overview exposes promises, manual/provider evidence, payment linking, separate financial approval/submission, AI review/extraction and deferred offers/returns/dispute panels. Operations uses six tabs without separate URLs. All are included in the manual and test matrix.

### Literal navigation targets (including nested links)

- `#access`: `frontend/app/page.tsx`
- `#docs-content`: `frontend/app/docs/layout.tsx`
- `#main-content`: `frontend/app/page.tsx`
- `#orders-content`: `frontend/components/merchant-orders.tsx`
- `#workflow`: `frontend/app/page.tsx`
- `#workspace-content`: `frontend/components/workspace.tsx`
- `/`: `frontend/app/docs/layout.tsx`, `frontend/app/not-found.tsx`, `frontend/app/page.tsx`, `frontend/components/customer-account.tsx`, `frontend/components/customer-view.tsx`, `frontend/components/merchant-login.tsx`, `frontend/components/merchant-orders.tsx`, `frontend/components/operations-console.tsx`, `frontend/components/workspace-account.tsx`, `frontend/components/workspace-shell.tsx`, `frontend/components/workspace.tsx`
- `/account`: `frontend/app/docs/layout.tsx`, `frontend/app/page.tsx`, `frontend/components/merchant-login.tsx`
- `/account?claim=1`: `frontend/components/operations-console.tsx`
- `/customer`: `frontend/app/not-found.tsx`, `frontend/app/page.tsx`, `frontend/components/customer-account.tsx`, `frontend/components/merchant-login.tsx`
- `/customer/account`: `frontend/app/page.tsx`, `frontend/components/customer-view.tsx`
- `/docs`: `frontend/app/docs/[slug]/page.tsx`, `frontend/app/docs/layout.tsx`, `frontend/app/page.tsx`, `frontend/components/docs-navigation.tsx`, `frontend/components/forms.tsx`, `frontend/components/merchant-login.tsx`, `frontend/components/operations-console.tsx`, `frontend/components/workspace-shell.tsx`, `frontend/components/workspace.tsx`
- `/docs/getting-started`: `frontend/app/docs/layout.tsx`, `frontend/app/docs/page.tsx`
- `/docs/resolve-guide.md`: `frontend/app/docs/[slug]/page.tsx`, `frontend/app/docs/page.tsx`, `frontend/components/docs-navigation.tsx`
- `/docs/resolve.openapi.json`: `frontend/app/docs/page.tsx`
- `/login`: `frontend/app/page.tsx`, `frontend/components/workspace-account.tsx`
- `/login?next=settings`: `frontend/components/merchant-login.tsx`, `frontend/components/merchant-sdk-keys.tsx`
- `/workspace`: `frontend/app/docs/layout.tsx`, `frontend/components/merchant-login.tsx`, `frontend/components/merchant-orders.tsx`, `frontend/components/operations-console.tsx`, `frontend/components/workspace-shell.tsx`
- `/workspace/operations`: `frontend/components/operations-console.tsx`, `frontend/components/workspace.tsx`
- `/workspace/orders`: `frontend/components/merchant-orders.tsx`, `frontend/components/operations-console.tsx`, `frontend/components/workspace-shell.tsx`, `frontend/components/workspace.tsx`
- `/workspace/settings`: `frontend/components/merchant-orders.tsx`, `frontend/components/operations-console.tsx`, `frontend/components/workspace-shell.tsx`, `frontend/components/workspace.tsx`
- `/workspace/settings#sdk-keys`: `frontend/components/merchant-orders.tsx`
- `http://127.0.0.1:8000/docs`: `frontend/components/ui.tsx`

## Forms and source-level input constraints

This exhaustive input-control inventory records literal attributes; conditional controls and service-level cross-field rules are defined in the linked source and OpenAPI schemas. HTML validation is usability support; backend validation remains authoritative.

| Component | Controls / validation attributes |
|---|---|
| `assurance.tsx` | name="enabled" type="checkbox"; type="number" name="days" min={1} max={365} required; name="fee" required; name="shipping"; type="checkbox" name="inspect"; type="checkbox" name="photos"; name="excluded"; name="instructions" required maxLength={3000}; name="instructions" required maxLength={3000}; name="address" maxLength={1000}; name="shipping"; name="label" type="file" accept="application/pdf" required; name="finding"; name="quantity" type="checkbox"; type="checkbox" name="evidence"; type="checkbox" name="override"; name="note" required maxLength={2000}; name="provider"; name="reference" required maxLength={100}; name="state"; name="note" required maxLength={2000}; name="refund" required maxLength={80}; name="type"; name="reference" required maxLength={100}; name="stage"; name="note" required maxLength={1000}; name="requirement"; name="evidence" type="checkbox"; name="note" required maxLength={2000} |
| `case-operations.tsx` | type="checkbox" name="promise"; type="datetime-local" name="expiry" required; name="dispute" required pattern="[A-Za-z0-9_-]+" maxLength={80}; name="reason" |
| `conversation.tsx` | maxLength={2000} |
| `customer-account.tsx` | name="email" type="email" maxLength={254} required |
| `customer-actions.tsx` | name="issue" required; name="description" maxLength={2000} required placeholder="Tell the merchant what happened. You can attach evidence after submitting."; name="evidence" type="file" accept=".pdf,.png,.jpg,.jpeg" required |
| `docs-navigation.tsx` | type="search" maxLength={100} placeholder="Find a guide…";  |
| `forms.tsx` | name="title" placeholder="e.g. Refund for a returned item" required maxLength={160}; name="order" placeholder="Order reference or PayPal order ID" maxLength={mode === "new" ? 100 : 160} required; name="payment_mode"; name="legacy_id"; name="legacy_manual" placeholder="Resolve case ID"; name="capture" required maxLength={100}; name="captured" placeholder="100.00" pattern="[0-9]+(\.[0-9]{1,2})?" required; name="promise_amount" placeholder="30.00" pattern="[0-9]+(\.[0-9]{1,2})?"; name="agreement" placeholder="Required if you entered an agreed refund" maxLength={3000}; ; name="promise" required maxLength={3000}; name={spec.key}; name={spec.key} placeholder={spec.hint} required pattern={spec.money ? "[0-9]+(\\.[0-9]{1,2} maxLength={160}; name="source_note" required maxLength={3000} placeholder="Quote or describe the recorded agreement."; name="reference" maxLength={160} placeholder="Support ticket or receipt ID"; type="datetime-local" name="due_at"; type="checkbox" name="requires"; name="finding"; name="note" required maxLength={3000}; name="reference" maxLength={160} placeholder="Warehouse or support reference"; name="refund_amount"; name="note" required maxLength={5000} placeholder="Why is this refund approved?"; name="note" required maxLength={1000} |
| `helpdesk-panel.tsx` | name="ticket" pattern="[1-9][0-9]{0,15}" required |
| `merchant-customer.tsx` | ; ; type="checkbox" |
| `merchant-login.tsx` | name="key" type={visible ? "text" : "password"} placeholder="rslv_…" maxLength={125} required |
| `merchant-orders.tsx` | placeholder="Order or PayPal ID" maxLength={160}; placeholder="All apps" maxLength={64} |
| `merchant-sdk-keys.tsx` | aria-label="SDK server environment" |
| `merchant-triage.tsx` | ; name="order" required maxLength={160} placeholder="e.g. ORD-4821"; name="email" type="email" maxLength={254} placeholder="buyer@example.com"; type="checkbox" name="send_email"; name="payment"; name="manual" placeholder="Resolve payment case ID"; type="checkbox" required; name="assignee" maxLength={80} placeholder="Name or team"; name="due_at" type="datetime-local"; name="waiting" type="checkbox" |
| `operations-console.tsx` | name={key} required maxLength={160}; name={key} type="password" maxLength={4096} placeholder={current ? "Leave blank to keep the saved value" : "Enter privately"}; type="checkbox" name="enabled"; type="checkbox" name="refunds_enabled"; type="checkbox" name="partial_refunds_enabled"; name="ticket" type="number" min={1} required; name="case" required; name="email" type="email" required; name="role"; aria-label="Private staff invitation"; name="role"; name="active" type="checkbox"; name="source" required pattern="[A-Za-z0-9][A-Za-z0-9_.-]{0,63}" maxLength={64}; type="password" aria-label="New SDK key" |
| `return-workflow.tsx` | ; aria-label={`Return quantity for ${i.name ?? i.product_id} type="number" name={i.product_id} min={0} max={i.available_quantity}; name="reason" maxLength={2000} required; ; name="carrier" required maxLength={60}; name="tracking_code" required maxLength={100}; name="reference" required maxLength={160}; name="promise_id"; name="note" required maxLength={2000} |
| `workspace-account.tsx` | name="workspace" maxLength={100} required; name="name" maxLength={100} required; type="email" name="email" maxLength={254} required; aria-label="Password" type="password" name="password" minLength={12} maxLength={256} required |
| `workspace.tsx` | aria-label="Search cases" placeholder="Search cases…" maxLength={160} |

## Authentication and roles

- Staff email/password: signup, login, invitation acceptance, legacy owner claim. Passwords require 12-256 characters and use scrypt; DB throttles authentication attempts. No forgot-password/reset UI or endpoint exists.
- Merchant access key -> 8-hour database-backed browser session. Optional PayPal identity must already be linked. HttpOnly SameSite=Lax cookie; HTTPS sets Secure. Logout/revocation ends access. Browser mutation gateways enforce exact Origin.
- Buyers use expiring/revocable case capabilities, isolated customer sessions from email/Google when configured, and order-bound intake links. Buyer links do not grant merchant access.
- Owner: all merchant actions; manager: operational writes and refund approvals, no refund submission or secret/team administration; finance: refund approval/submission, dispute state/tracing; agent: ordinary case work; viewer: reads only. Owners/managers review dispute packages. Owner alone changes return policy/connections/keys/team. Backend enforcement is authoritative; legacy full merchant keys have owner authority.
- SDK commerce keys are restricted; support grants bind a key to one app source. The integrating application must establish the buyer's order ownership. No public end-customer registration exists.

## Integrations

PayPal Sandbox OAuth/capture/order/refund/history/webhook verification; separate optional PayPal merchant identity; Google OIDC for buyers; Resend or SMTP/Nodemailer notices; Zendesk imports/webhooks; Shopify Admin GraphQL and EasyPost evidence reads; advisory Groq/OpenRouter inference. Optional features default off except workspace signup. No Stripe, bank receipt verification, live PayPal refund execution, label purchasing or automatic dispute submission exists.

## API endpoint inventory

Each operation below is sourced from the canonical FastAPI-generated contract. Security denotes declared auth; public capability endpoints still validate tokens/signatures in application code.

| Method | Path | Operation | Declared security |
|---|---|---|---|
| GET | `/health` | Health | Token/signature or public (see source) |
| POST | `/health` | Health | Token/signature or public (see source) |
| GET | `/ready` | Readiness | Token/signature or public (see source) |
| POST | `/cases` | Create Case | MerchantBearer |
| GET | `/cases` | List Cases | MerchantBearer |
| GET | `/cases/{case_id}` | Get Case | MerchantBearer |
| PUT | `/cases/{case_id}/commitment` | Update Commitment | MerchantBearer |
| GET | `/cases/{case_id}/timeline` | Get Timeline | MerchantBearer |
| POST | `/cases/{case_id}/refunds` | Record Refund | MerchantBearer |
| GET | `/cases/{case_id}/refunds` | List Refunds | MerchantBearer |
| PATCH | `/cases/{case_id}/refunds/{refund_id}` | Update Refund Status | MerchantBearer |
| POST | `/cases/{case_id}/condition-checks` | Record Condition Check | MerchantBearer |
| GET | `/cases/{case_id}/condition-checks` | List Condition Checks | MerchantBearer |
| GET | `/cases/{case_id}/reconciliation` | Get Reconciliation | MerchantBearer |
| GET | `/auth/me` | Get Identity | MerchantBearer |
| POST | `/cases/{case_id}/paypal-capture-verifications` | Verify Paypal Capture | MerchantBearer |
| GET | `/cases/{case_id}/paypal-capture-verifications` | List Paypal Capture Verifications | MerchantBearer |
| POST | `/cases/{case_id}/refund-approvals` | Create Refund Approval | MerchantBearer |
| GET | `/cases/{case_id}/refund-approvals` | List Refund Approvals | MerchantBearer |
| GET | `/cases/{case_id}/refund-approvals/{approval_id}` | Get Refund Approval | MerchantBearer |
| POST | `/cases/{case_id}/refund-approvals/{approval_id}/revoke` | Revoke Refund Approval | MerchantBearer |
| GET | `/cases/{case_id}/refund-approvals/{approval_id}/events` | Get Refund Approval Events | MerchantBearer |
| POST | `/cases/{case_id}/refund-executions` | Execute Refund | MerchantBearer |
| GET | `/cases/{case_id}/refund-executions` | List Refund Executions | MerchantBearer |
| GET | `/cases/{case_id}/refund-executions/{execution_id}` | Get Refund Execution | MerchantBearer |
| POST | `/cases/{case_id}/refund-executions/{execution_id}/retry` | Retry Refund Execution | MerchantBearer |
| POST | `/cases/{case_id}/refund-executions/{execution_id}/refresh` | Refresh Refund Execution | MerchantBearer |
| GET | `/cases/{case_id}/refund-executions/{execution_id}/events` | Get Execution Events | MerchantBearer |
| POST | `/cases/{case_id}/paypal-refund-verifications` | Verify Paypal Refund | MerchantBearer |
| GET | `/cases/{case_id}/paypal-refund-verifications` | List Paypal Refund Verifications | MerchantBearer |
| POST | `/webhooks/paypal/sandbox` | Receive Paypal Webhook | Token/signature or public (see source) |
| POST | `/cases/{case_id}/paypal-refund-history/refresh` | Refresh Paypal History | MerchantBearer |
| POST | `/cases/{case_id}/close` | Close Case | MerchantBearer |
| POST | `/cases/{case_id}/reopen` | Reopen Case | MerchantBearer |
| POST | `/cases/{case_id}/attachments` | Upload Attachment | MerchantBearer |
| GET | `/cases/{case_id}/attachments` | List Attachments | MerchantBearer |
| GET | `/cases/{case_id}/attachments/{attachment_id}` | Download Attachment | MerchantBearer |
| GET | `/review-queue` | Get Review Queue | MerchantBearer |
| POST | `/review-queue/{exception_id}/resolve` | Resolve Exception | MerchantBearer |
| GET | `/resolution-cases/inbox` | Merchant Inbox | MerchantBearer |
| GET | `/resolution-cases/{case_id}/customer-link` | Customer Link Status | MerchantBearer |
| POST | `/resolution-cases/{case_id}/customer-link` | Issue Customer Link | MerchantBearer |
| DELETE | `/resolution-cases/{case_id}/customer-link` | Revoke Customer Link | MerchantBearer |
| GET | `/resolution-cases/{case_id}/helpdesk` | Read Helpdesk | MerchantBearer |
| PUT | `/resolution-cases/{case_id}/helpdesk` | Link Helpdesk | MerchantBearer |
| GET | `/resolution-cases/{case_id}/customer-messages` | Merchant Read Messages | MerchantBearer |
| POST | `/resolution-cases/{case_id}/customer-messages` | Merchant Send Message | MerchantBearer |
| POST | `/customer-portal/view` | Customer View | Token/signature or public (see source) |
| POST | `/customer-portal/messages` | Customer Send Message | Token/signature or public (see source) |
| POST | `/resolution-cases/intake-invites` | Create Intake Invite | MerchantBearer |
| GET | `/customer-account/capabilities` | Customer Account Capabilities | Token/signature or public (see source) |
| POST | `/customer-account/google/start` | Start Google Sign In | Token/signature or public (see source) |
| POST | `/customer-account/google/finish` | Finish Google Sign In | Token/signature or public (see source) |
| POST | `/customer-account/request-sign-in` | Request Customer Sign In | Token/signature or public (see source) |
| POST | `/customer-account/redeem` | Redeem Customer Sign In | Token/signature or public (see source) |
| GET | `/customer-account/cases` | List Customer Account Cases | Token/signature or public (see source) |
| POST | `/customer-account/cases/{case_id}/open` | Open Customer Account Case | Token/signature or public (see source) |
| POST | `/customer-account/sign-out` | Customer Sign Out | Token/signature or public (see source) |
| POST | `/customer-portal/intake-view` | Intake View | Token/signature or public (see source) |
| POST | `/customer-portal/intake` | Submit Intake | Token/signature or public (see source) |
| POST | `/customer-portal/evidence` | Customer Upload Evidence | Token/signature or public (see source) |
| POST | `/customer-portal/evidence/{file_id}` | Buyer Download Evidence | Token/signature or public (see source) |
| GET | `/resolution-cases/{case_id}/customer-evidence` | Merchant Customer Evidence | MerchantBearer |
| GET | `/resolution-cases/{case_id}/customer-evidence/{file_id}` | Merchant Download Evidence | MerchantBearer |
| GET | `/resolution-cases/{case_id}/operations` | Case Operations | MerchantBearer |
| PUT | `/resolution-cases/{case_id}/operations` | Update Case Operations | MerchantBearer |
| POST | `/resolution-cases/{case_id}/operations/read` | Mark Customer Messages Read | MerchantBearer |
| GET | `/merchant-auth/capabilities` | Capabilities | Token/signature or public (see source) |
| POST | `/merchant-auth/session/key` | Key Login | Token/signature or public (see source) |
| GET | `/merchant-auth/session` | Merchant Session | MerchantBearer |
| DELETE | `/merchant-auth/session` | Logout | MerchantBearer |
| POST | `/merchant-auth/paypal/start` | Start Paypal | MerchantBearer |
| POST | `/merchant-auth/paypal/finish` | Finish Paypal | MerchantBearer |
| DELETE | `/merchant-auth/paypal/link` | Unlink Paypal | MerchantBearer |
| GET | `/merchant-auth/commerce-keys` | List Commerce Keys | MerchantBearer |
| POST | `/merchant-auth/commerce-keys` | Issue Commerce Key | MerchantBearer |
| DELETE | `/merchant-auth/commerce-keys/{key_id}` | Revoke Commerce Key | MerchantBearer |
| GET | `/resolution-cases/promise-health` | Promises Needing Attention | MerchantBearer |
| GET | `/resolution-cases/{case_id}/promise-health` | Case Promise Health | MerchantBearer |
| GET | `/resolution-cases/{case_id}/next-action` | Case Next Action | MerchantBearer |
| POST | `/resolution-cases` | Create Resolution | MerchantBearer |
| GET | `/resolution-cases` | List Resolutions | MerchantBearer |
| POST | `/resolution-cases/upsert` | Upsert Evidence Case | MerchantBearer |
| GET | `/resolution-cases/{case_id}` | Get Resolution | MerchantBearer |
| POST | `/resolution-cases/{case_id}/evidence/records` | Link Evidence Record | MerchantBearer |
| POST | `/resolution-cases/{case_id}/evidence/events` | Submit Merchant Evidence | MerchantBearer |
| POST | `/resolution-cases/{case_id}/evidence/refresh` | Refresh Case Evidence | MerchantBearer |
| PUT | `/resolution-cases/{case_id}/payment-link` | Link Resolution Payment | MerchantBearer |
| POST | `/resolution-cases/{case_id}/promises` | Record Promise | MerchantBearer |
| PUT | `/resolution-cases/{case_id}/promises/{promise_id}` | Revise Promise | MerchantBearer |
| POST | `/resolution-cases/{case_id}/promises/{promise_id}/evidence` | Record Promise Evidence | MerchantBearer |
| POST | `/resolution-cases/{case_id}/promises/{promise_id}/refresh` | Refresh Promise | MerchantBearer |
| GET | `/resolution-cases/{case_id}/timeline` | Resolution Timeline | MerchantBearer |
| GET | `/resolution-cases/{case_id}/evidence-bundle` | Evidence Bundle | MerchantBearer |
| POST | `/commerce/orders/sync` | Sync Commerce Order | MerchantBearer |
| POST | `/commerce/orders/register` | Register Commerce Order | MerchantBearer |
| GET | `/commerce/orders` | List Commerce Orders | MerchantBearer |
| GET | `/commerce/orders/{order_id}` | Get Registered Order | MerchantBearer |
| POST | `/commerce/orders/{order_id}/case` | Open Commerce Case | MerchantBearer |
| GET | `/resolution-cases/{case_id}/commerce` | Get Commerce Order | MerchantBearer |
| POST | `/resolution-cases/{case_id}/commerce/refresh` | Refresh Commerce Order | MerchantBearer |
| GET | `/resolution-cases/{case_id}/commerce/contact` | Get Commerce Contact | MerchantBearer |
| GET | `/resolution-cases/{case_id}/investigations` | Investigations | MerchantBearer |
| POST | `/resolution-cases/{case_id}/investigations/{investigation_id}/review` | Review Investigation | MerchantBearer |
| POST | `/resolution-cases/{case_id}/ai/extract-promises` | Extract Promise Proposals | MerchantBearer |
| GET | `/ai/usage` | Extraction Usage | MerchantBearer |
| POST | `/resolution-cases/{case_id}/ai/explain-next-action` | Explain Next Action | MerchantBearer |
| POST | `/platform/account/signup` | Signup | Token/signature or public (see source) |
| POST | `/platform/account/login` | Login | Token/signature or public (see source) |
| POST | `/platform/account/claim` | Claim Owner | MerchantBearer |
| POST | `/platform/account/accept-invite` | Accept Invite | Token/signature or public (see source) |
| GET | `/platform/me` | Me | MerchantBearer |
| GET | `/platform/team` | Team | MerchantBearer |
| POST | `/platform/team/invites` | Invite | MerchantBearer |
| PUT | `/platform/team/{staff_id}` | Update Staff | MerchantBearer |
| GET | `/platform/audit` | Audit History | MerchantBearer |
| GET | `/platform/sdk-keys` | Sdk Keys | MerchantBearer |
| POST | `/platform/sdk-keys` | Issue Sdk Key | MerchantBearer |
| POST | `/platform/support-keys` | Issue Support Key | MerchantBearer |
| DELETE | `/platform/sdk-keys/{key_id}` | Revoke Sdk Key | MerchantBearer |
| GET | `/platform/connections` | Connections | MerchantBearer |
| PUT | `/platform/connections/{provider}` | Save Connection | MerchantBearer |
| POST | `/platform/connections/{provider}/check` | Check Connection | MerchantBearer |
| GET | `/platform/imports` | Imports | MerchantBearer |
| POST | `/platform/imports/zendesk` | Import Ticket | MerchantBearer |
| GET | `/platform/imports/{import_id}` | Imported Ticket | MerchantBearer |
| PUT | `/platform/imports/{import_id}/match` | Match Ticket | MerchantBearer |
| GET | `/platform/dashboard` | Dashboard | MerchantBearer |
| GET | `/platform/watchdog` | Watchdog | MerchantBearer |
| POST | `/platform/watchdog/scan` | Scan | MerchantBearer |
| GET | `/platform/cases/{case_id}/offers` | Offers | MerchantBearer |
| POST | `/platform/cases/{case_id}/offers` | Publish Offer | MerchantBearer |
| GET | `/platform/cases/{case_id}/support-requests` | Case Support Requests | MerchantBearer |
| GET | `/platform/cases/{case_id}/returns` | Returns | MerchantBearer |
| POST | `/platform/cases/{case_id}/returns` | Request Return | MerchantBearer |
| PUT | `/platform/cases/{case_id}/returns/{return_id}` | Progress Return | MerchantBearer |
| GET | `/platform/cases/{case_id}/dispute-packages` | Packages | MerchantBearer |
| POST | `/platform/cases/{case_id}/dispute-packages` | Build Package | MerchantBearer |
| GET | `/platform/cases/{case_id}/dispute-packages/{package_id}` | Read Package | MerchantBearer |
| POST | `/platform/cases/{case_id}/dispute-packages/{package_id}/review` | Review Package | MerchantBearer |
| GET | `/platform/cases/{case_id}/dispute-packages/{package_id}/export` | Export Package | MerchantBearer |
| POST | `/platform/buyer/offers` | Buyer Offers | Token/signature or public (see source) |
| POST | `/platform/buyer/decision` | Buyer Decision | Token/signature or public (see source) |
| POST | `/platform/buyer/returns` | Buyer Returns | Token/signature or public (see source) |
| POST | `/platform/buyer/returns/request` | Buyer Request Return | Token/signature or public (see source) |
| POST | `/aftercare/issues` | Open Aftercare Issue | MerchantBearer |
| POST | `/aftercare/status` | Aftercare Status | MerchantBearer |
| POST | `/aftercare/portal` | Aftercare Portal | MerchantBearer |
| GET | `/platform/return-policy` | Policy | MerchantBearer |
| PUT | `/platform/return-policy` | Policy Save | MerchantBearer |
| POST | `/cases/{case_id}/disputes` | Dispute Record | MerchantBearer |
| GET | `/cases/{case_id}/disputes` | Dispute List | MerchantBearer |
| GET | `/platform/cases/{case_id}/disputes` | Resolution Disputes | MerchantBearer |
| POST | `/platform/cases/{case_id}/disputes` | Resolution Dispute Record | MerchantBearer |
| POST | `/platform/cases/{case_id}/refund-traces` | Trace Record | MerchantBearer |
| POST | `/platform/cases/{case_id}/dispute-documents` | Dispute Document | MerchantBearer |
| GET | `/platform/cases/{case_id}/returns/{return_id}/guide` | Return Guide | MerchantBearer |
| PUT | `/platform/cases/{case_id}/returns/{return_id}/guide` | Save Return Guide | MerchantBearer |
| POST | `/platform/cases/{case_id}/returns/{return_id}/inspection` | Inspect Return | MerchantBearer |
| POST | `/platform/cases/{case_id}/returns/{return_id}/labels` | Upload Label | MerchantBearer |
| POST | `/aftercare/journey` | Refund Journey | MerchantBearer |
| POST | `/aftercare/context` | Support Context | MerchantBearer |
| POST | `/aftercare/received` | Received Refund | MerchantBearer |
| POST | `/aftercare/issues/lookup` | Issue Lookup | MerchantBearer |
| POST | `/aftercare/events` | Event Pull | MerchantBearer |
| POST | `/aftercare/returns/eligibility` | Check Eligibility | MerchantBearer |
| POST | `/aftercare/returns` | Support Returns | MerchantBearer |
| POST | `/aftercare/returns/request` | Support Return Request | MerchantBearer |
| POST | `/aftercare/returns/guide` | Support Return Guide | MerchantBearer |
| POST | `/aftercare/returns/label` | Support Label | MerchantBearer |
| POST | `/platform/buyer/assurance` | Buyer Assurance | Token/signature or public (see source) |
| POST | `/platform/buyer/returns/guide` | Buyer Guide | Token/signature or public (see source) |
| POST | `/platform/buyer/returns/label` | Buyer Label | Token/signature or public (see source) |
| POST | `/platform/buyer/return-policy` | Buyer Return Policy | Token/signature or public (see source) |
| POST | `/webhooks/zendesk/{merchant_id}` | Zendesk Hook | Token/signature or public (see source) |

Total: **175 operations** across **150 API paths**.

## Frontend API gateways and webhook routes

Next.js entry points constrain downstream paths, credentials, origins and body sizes. Server-only service addresses/secrets are not client configuration.

| Route | Exported methods | Source |
|---|---|---|
| `/api/auth/paypal/[action]` | POST, GET, DELETE | `frontend/app/api/auth/paypal/[action]/route.ts` |
| `/api/customer-account/[...path]` | GET, POST | `frontend/app/api/customer-account/[...path]/route.ts` |
| `/api/customer-portal/[...path]` | POST | `frontend/app/api/customer-portal/[...path]/route.ts` |
| `/api/platform/[...path]` | GET, POST, PUT, DELETE | `frontend/app/api/platform/[...path]/route.ts` |
| `/api/platform-account/[action]` | POST | `frontend/app/api/platform-account/[action]/route.ts` |
| `/api/platform-buyer/[...path]` | POST | `frontend/app/api/platform-buyer/[...path]/route.ts` |
| `/api/resolve/[...path]` | GET, POST, PUT, DELETE | `frontend/app/api/resolve/[...path]/route.ts` |
| `/api/sdk/[...path]` | GET, POST | `frontend/app/api/sdk/[...path]/route.ts` |
| `/api/session` | GET, POST, DELETE | `frontend/app/api/session/route.ts` |
| `/webhooks/zendesk/[merchant]` | POST | `frontend/app/webhooks/zendesk/[merchant]/route.ts` |

## Database operation inventory

Database operations reside in services, not only route handlers. Tables and mutations below are extracted statically from backend Python/SQL; dynamically built queries must also be reviewed in their source.

| Table | Observed SQL operations |
|---|---|
| `aftercare_apps` | CREATE TABLE, INSERT INTO, SELECT |
| `aftercare_issues` | CREATE TABLE, INSERT INTO, SELECT |
| `assurance_dispute_events` | CREATE TABLE, INSERT INTO, SELECT |
| `assurance_disputes` | CREATE TABLE, INSERT INTO, SELECT |
| `assurance_events` | CREATE TABLE, INSERT INTO, SELECT |
| `assurance_policies` | CREATE TABLE, INSERT INTO, SELECT |
| `assurance_projections` | CREATE TABLE, INSERT INTO, SELECT, UPDATE |
| `assurance_receipts` | CREATE TABLE, INSERT INTO, SELECT |
| `assurance_refund_traces` | CREATE TABLE, INSERT INTO, SELECT |
| `assurance_return_guides` | CREATE TABLE, INSERT INTO, SELECT |
| `assurance_return_labels` | CREATE TABLE, INSERT INTO, SELECT |
| `assurance_return_reviews` | CREATE TABLE, INSERT INTO, SELECT |
| `captures` | CREATE TABLE, INSERT INTO, SELECT, UPDATE |
| `case_attachments` | CREATE TABLE, INSERT INTO, SELECT |
| `case_events` | CREATE TABLE, INSERT INTO, SELECT |
| `cases` | CREATE TABLE, INSERT INTO, SELECT, UPDATE |
| `commerce_order_snapshots` | CREATE TABLE, CREATE TABLE IF NOT EXISTS, SELECT |
| `commerce_orders` | CREATE TABLE, INSERT INTO, SELECT, UPDATE |
| `condition_checks` | CREATE TABLE, INSERT INTO, SELECT |
| `customer_account_links` | CREATE TABLE, DELETE FROM, INSERT INTO, SELECT |
| `customer_case_contacts` | CREATE TABLE, INSERT INTO, SELECT |
| `customer_evidence` | CREATE TABLE, INSERT INTO, SELECT |
| `customer_google_flows` | CREATE TABLE, DELETE FROM, INSERT INTO, SELECT |
| `customer_intake_invites` | CREATE TABLE, INSERT INTO, SELECT, UPDATE |
| `customer_mail_outbox` | CREATE TABLE, INSERT INTO, SELECT, UPDATE |
| `customer_portal_links` | CREATE TABLE, INSERT INTO, SELECT, UPDATE |
| `customer_portal_messages` | CREATE TABLE, INSERT INTO, SELECT |
| `customer_sessions` | CREATE TABLE, DELETE FROM, INSERT INTO, SELECT |
| `customer_signins` | CREATE TABLE, DELETE FROM, INSERT INTO, SELECT, UPDATE |
| `information_schema` | SELECT |
| `investigation_audit` | CREATE TABLE, INSERT INTO |
| `investigation_jobs` | CREATE TABLE, INSERT INTO, SELECT, UPDATE |
| `investigation_reviews` | CREATE TABLE, INSERT INTO, SELECT |
| `investigations` | CREATE TABLE, INSERT INTO, SELECT |
| `legacy_captures` | SELECT |
| `legacy_cases` | SELECT |
| `legacy_condition_checks` | SELECT |
| `legacy_refunds` | SELECT |
| `merchant_api_keys` | CREATE TABLE, INSERT INTO, SELECT, UPDATE |
| `merchant_paypal_flows` | CREATE TABLE, DELETE FROM, INSERT INTO, SELECT, UPDATE |
| `merchant_paypal_links` | CREATE TABLE, DELETE FROM, INSERT INTO, SELECT |
| `merchant_web_sessions` | CREATE TABLE, DELETE FROM, INSERT INTO, SELECT |
| `merchants` | CREATE TABLE, DELETE FROM, INSERT INTO, SELECT |
| `paypal_capture_verifications` | CREATE TABLE, INSERT INTO, SELECT |
| `paypal_refund_history` | CREATE TABLE, INSERT INTO, SELECT |
| `paypal_refund_verifications` | CREATE TABLE, INSERT INTO, SELECT |
| `paypal_refund_verifications_v7` | SELECT |
| `paypal_webhook_events` | CREATE TABLE, INSERT INTO, SELECT, UPDATE |
| `pg_constraint` | SELECT |
| `pg_trigger` | SELECT |
| `platform_alerts` | CREATE TABLE, INSERT INTO, SELECT, UPDATE |
| `platform_audit` | CREATE TABLE, INSERT INTO, SELECT |
| `platform_auth_limits` | CREATE TABLE, INSERT INTO, SELECT |
| `platform_connections` | CREATE TABLE, INSERT INTO, SELECT, UPDATE |
| `platform_imports` | CREATE TABLE, INSERT INTO, SELECT, UPDATE |
| `platform_invites` | CREATE TABLE, INSERT INTO, SELECT, UPDATE |
| `platform_offers` | CREATE TABLE, INSERT INTO, SELECT, UPDATE |
| `platform_packages` | CREATE TABLE, INSERT INTO, SELECT, UPDATE |
| `platform_returns` | CREATE TABLE, INSERT INTO, SELECT, UPDATE |
| `platform_sessions` | CREATE TABLE, DELETE FROM, INSERT INTO, SELECT |
| `platform_staff` | CREATE TABLE, INSERT INTO, SELECT, UPDATE |
| `platform_ticket_messages` | CREATE TABLE, INSERT INTO, SELECT |
| `platform_webhook_jobs` | CREATE TABLE, INSERT INTO, SELECT, UPDATE |
| `pragma_table_info` | SELECT |
| `provider_refresh_schedule` | CREATE TABLE, INSERT INTO, UPDATE |
| `refund_approval_events` | CREATE TABLE, INSERT INTO, SELECT |
| `refund_approvals` | CREATE TABLE, INSERT INTO, SELECT, UPDATE |
| `refund_execution_events` | CREATE TABLE, INSERT INTO, SELECT |
| `refund_execution_events_v7` | SELECT |
| `refund_executions` | CREATE TABLE, INSERT INTO, SELECT, UPDATE |
| `refund_executions_v7` | SELECT |
| `refunds` | CREATE TABLE, INSERT INTO, SELECT, UPDATE |
| `resolution_cases` | CREATE TABLE, INSERT INTO, SELECT, UPDATE |
| `resolution_events` | CREATE TABLE, INSERT INTO, SELECT |
| `resolution_evidence_events` | CREATE TABLE, INSERT INTO, SELECT |
| `resolution_evidence_links` | CREATE TABLE, INSERT INTO, SELECT |
| `resolution_evidence_refs` | CREATE TABLE, INSERT INTO, SELECT |
| `resolution_evidence_state` | CREATE TABLE, INSERT INTO, SELECT |
| `resolution_helpdesk` | CREATE TABLE, INSERT INTO, SELECT |
| `resolution_operations` | CREATE TABLE, INSERT INTO, SELECT, UPDATE |
| `resolution_promises` | CREATE TABLE, INSERT INTO, SELECT, UPDATE |
| `review_exceptions` | CREATE TABLE, INSERT INTO, SELECT, UPDATE |
| `schema_migrations` | CREATE TABLE IF NOT EXISTS, INSERT INTO, SELECT |
| `sqlite_master` | SELECT |
| `sqlite_sequence` | SELECT |

## Environment variables (names only)

Never copy configured values into documentation. Ordinary API settings use backend dotenv/process environment; inference settings use process environment only. Frontend gateways read only server variables. Provider-specific required combinations are documented in `.env.example` and the existing integration guides.

- `RESOLVE_DATABASE_PATH` (Path)
- `RESOLVE_DATABASE_URL` (SecretStr | None)
- `RESOLVE_MERCHANT_WEB_ORIGIN` (str | None)
- `RESOLVE_PAYPAL_LOGIN_ENABLED` (bool)
- `RESOLVE_PAYPAL_LOGIN_ENVIRONMENT` (Literal['sandbox', 'live'])
- `RESOLVE_PAYPAL_LOGIN_CLIENT_ID` (SecretStr | None)
- `RESOLVE_PAYPAL_LOGIN_CLIENT_SECRET` (SecretStr | None)
- `RESOLVE_PAYPAL_SANDBOX_ENABLED` (bool)
- `RESOLVE_PAYPAL_SANDBOX_REFUNDS_ENABLED` (bool)
- `RESOLVE_PAYPAL_SANDBOX_PARTIAL_REFUNDS_ENABLED` (bool)
- `RESOLVE_PAYPAL_SANDBOX_WEBHOOK_ID` (str | None)
- `RESOLVE_PAYPAL_RESOLVE_MERCHANT_ID` (UUID | None)
- `RESOLVE_PAYPAL_SANDBOX_CLIENT_ID` (SecretStr | None)
- `RESOLVE_PAYPAL_SANDBOX_CLIENT_SECRET` (SecretStr | None)
- `RESOLVE_PAYPAL_SANDBOX_MERCHANT_ID` (str | None)
- `RESOLVE_RESOLUTION_CONNECTOR_MERCHANT_ID` (UUID | None)
- `RESOLVE_SHOPIFY_SHOP_DOMAIN` (str | None)
- `RESOLVE_SHOPIFY_ADMIN_TOKEN` (SecretStr | None)
- `RESOLVE_EASYPOST_API_KEY` (SecretStr | None)
- `RESOLVE_AUTO_PROVIDER_REFRESH_ENABLED` (bool)
- `RESOLVE_PROMISE_OVERDUE_DAYS` (int)
- `RESOLVE_CUSTOMER_EMAIL_ENABLED` (bool)
- `RESOLVE_CUSTOMER_EMAIL_TRANSPORT` (Literal['resend', 'smtp'])
- `RESOLVE_CUSTOMER_EMAIL_MERCHANT_ID` (UUID | None)
- `RESOLVE_CUSTOMER_PUBLIC_ORIGIN` (str | None)
- `RESOLVE_CUSTOMER_SIGNING_KEY` (SecretStr | None)
- `RESOLVE_RESEND_API_KEY` (SecretStr | None)
- `RESOLVE_RESEND_FROM` (str | None)
- `RESOLVE_SMTP_HOST` (str | None)
- `RESOLVE_SMTP_PORT` (int)
- `RESOLVE_SMTP_SECURE` (bool)
- `RESOLVE_SMTP_USER` (str | None)
- `RESOLVE_SMTP_PASSWORD` (SecretStr | None)
- `RESOLVE_SMTP_FROM` (str | None)
- `RESOLVE_CUSTOMER_GOOGLE_ENABLED` (bool)
- `RESOLVE_GOOGLE_CLIENT_ID` (SecretStr | None)
- `RESOLVE_GOOGLE_CLIENT_SECRET` (SecretStr | None)
- `RESOLVE_HELPDESK_MERCHANT_ID` (UUID | None)
- `RESOLVE_ZENDESK_SUBDOMAIN` (str | None)
- `RESOLVE_ZENDESK_OAUTH_TOKEN` (SecretStr | None)
- `RESOLVE_PLATFORM_ENCRYPTION_KEY` (SecretStr | None)
- `RESOLVE_MERCHANT_SIGNUP_ENABLED` (bool)

Additional directly referenced process variables: `GROQ_DATA_POLICY`, `RESOLVE_AI_`, `RESOLVE_AI_DATA_POLICY`, `RESOLVE_AI_GROQ_KEY`, `RESOLVE_AI_TIMEOUT_SECONDS`, `RESOLVE_BACKEND_ALLOW_PRIVATE_HTTP`, `RESOLVE_BACKEND_URL`, `RESOLVE_CUSTOMER_PUBLIC_ORIGIN`, `RESOLVE_DATABASE_PATH`, `RESOLVE_DATABASE_URL`, `RESOLVE_EXTRACTION_`, `RESOLVE_ISOLATED_TEST`, `RESOLVE_MERCHANT_WEB_ORIGIN`, `RESOLVE_PLATFORM_ENCRYPTION_KEY`.

## Startup and pre-existing deployment state

Backend: `cd backend; uv sync --locked; uv run uvicorn app.main:app --host 127.0.0.1 --port 8000`. Frontend: `npm --prefix frontend ci`, `npm --prefix frontend run build:preview`, then `npm --prefix frontend run preview`. Four workers: `app.worker`, `app.followup_worker`, `app.investigation_worker`, `app.operations_worker` (each supports `--loop`).

At audit start there was no Dockerfile, infrastructure manifest or CI workflow. Hosted setup existed only as instructions and `start:hosted`. The owner has an existing configured runtime; all audit tests must use isolated settings and disposable databases. Existing dirty files are preserved. The checkout-store example is a separate sample with its own README, database and deployment lifecycle.

## Separate checkout-store example

`examples/checkout-store` is a standalone Node 24 HTTP server with built-in SQLite, six-product catalog, cart, Sandbox redirect/capture, receipt and embedded order support. It is not a hidden Resolve dashboard and is not deployed by the main Render Blueprint. Its browser page is `/`; catalog/cart/receipt/support are states within that page. Static assets are local CSS/JS/SVG. The browser owns receipts through an HttpOnly session; another browser gets 404. Server-side quoting rejects client-supplied prices and capture retries reuse identity. Shipping is not implemented.

Its API routes are `GET /api/catalog`, `POST /api/orders`, `GET /api/orders/{id}`, and `POST /api/orders/{id}/{action}` for `capture`, `verify`, `support`, `resolution`, `support-link`, `refund-journey`, `context`, and `return-eligibility`. Store-specific `SHOP_*` settings and Resolve integration values are documented in its README/source. These are additional to the 175 FastAPI operations above. The PayPal approval page used in the test is a mock redirect, not an application route or actual PayPal account consent.
