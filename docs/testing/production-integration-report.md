# Real-service and production integration verification

Evidence date: 11 November 2026. **No hosted production release exists in this audit.** VERIFIED below is explicitly scoped to the named real service/environment, never inferred from compilation, a fixture or a mock. No production payment credentials or real-money operation was used. Configured secret values remain private.

## Integration classification

| Integration / scope | Status | Actual evidence and remaining work |
|---|---|---|
| PayPal Sandbox order → buyer approval → capture → full refund | VERIFIED | Owner explicitly approved one USD 1.00 workflow, then personally completed Sandbox approval. Official OAuth returned 200; order creation returned 201; independently read APPROVED amount/currency/seller matched; capture returned 201. Existing backend verified the capture/history, created a separate exact approval and submitted one full refund. Independent refund GET reported COMPLETED USD 1.00. Reconciliation fulfilled, remaining USD 0.00, one persisted refund. Read-only repeat verification did not create another execution/refund. This is Sandbox only. |
| Resolve SDK against the real disposable API | VERIFIED | Existing Sandbox store adapter and first-party Node SDK 0.7.0 registered the actual order, captured amount and final refunded snapshot. Browser read-back asserted actual capture ID, USD 1.00 captured/refunded and refunded state; customer totals matched. Financial execution used the backend's guarded API, not an SDK shortcut. Hosted SDK connectivity and restricted-key account setup remain separate checks. |
| PayPal Sandbox negative authentication | VERIFIED | Deliberate invalid bearer GET to the official Sandbox captures endpoint returned 401. No production credentials used. Expired tokens/rate-limit/timeouts are covered by controlled tests, not induced on the real service. |
| PayPal signed webhook delivery | BLOCKED | Repository-owned TLS stand-ins test signatures/replays/failures. No reachable deployed callback or actual provider delivery has been verified. Configure real webhook ID, callback and app/merchant binding, then deliver an official Sandbox event. |
| PayPal merchant identity login | BLOCKED | Credential/origin presence observed, but real OAuth account consent/callback was not performed. Controlled browser checks are separate evidence. |
| Google buyer identity | BLOCKED | Google client ID and secret absent from the inspected ordinary configuration; actual registered HTTPS callback and verified buyer consent required. |
| Shopify order evidence | BLOCKED | Shop domain/admin token/Resolve connector merchant binding absent. No actual Shopify response verified. |
| EasyPost tracking | BLOCKED | API key and Resolve connector merchant binding absent. No actual tracker response verified. No shipment or label purchase is implemented/claimed. |
| Zendesk ticket import/webhook | BLOCKED | Subdomain/OAuth token/helpdesk merchant binding absent. Real account scopes, matching and signed delivery need verification. |
| Resend email | BLOCKED | API key/from/signing/origin names present; validity/delivery not checked. Production credential use and delivery were not authorized. A verified sender and approved recipient are required. |
| SMTP / Nodemailer | BLOCKED | Host/user/password/from/signing/origin names present, but authentication and delivery were not attempted with production credentials. Requires approved delivery test and Node mailer runtime. |
| Groq official SDK / bounded investigation HTTP adapter | PARTIALLY VERIFIED | Updated 12 November, CHG-059/060: the owner enabled AI; actual configured Groq authentication, a guarded SDK advisory response and a real GPT-OSS120B automatic investigation passed against an isolated copy of the filmed Sandbox case. Three official provider findings, finished/no-action result, audited verified-snapshot read and zero financial writes. Earlier redundant-read stops are retained. This is not verification of all model/error/production scenarios. |
| OpenRouter deeper investigation | BLOCKED | Not exercised in the new account-backed filming run. Pinned route/privacy/price controls and controlled failure tests do not establish actual account-side availability or successful escalation. |
| PostgreSQL | PARTIALLY VERIFIED | Actual disposable loopback PostgreSQL 18 migration/concurrency/pool tests: 12 passed in this run. Hosted configured owner storage was deliberately not accessed. Managed production instance/TLS/backups/restore/latency still unverified. |
| Render website/API/workers | BLOCKED | Render API token/account-side access, reviewed published source and billing authorization unavailable. Blueprint/instructions exist; no deployed URLs or production requests are fabricated. |

No actual integration failure remains in the authorized Sandbox flow. BLOCKED means missing configuration, deployment, consent or permitted external action; it does not mean a controlled mock passed the real provider.

## Credentials and locations

Backend ordinary settings load process environment or `backend/.env`; deployment values belong in Render's secret controls on API/appropriate workers. Optional per-workspace provider credentials are saved encrypted through Operations → Connections. AI settings read process environment only. Frontend **server** settings use `frontend/.env.local`/Render; never expose provider secrets with `NEXT_PUBLIC_*`. Integrating stores keep SDK credentials on their own server.

| Integration | Required names / configuration |
|---|---|
| PayPal Sandbox | `RESOLVE_PAYPAL_SANDBOX_CLIENT_ID`, `RESOLVE_PAYPAL_SANDBOX_CLIENT_SECRET`, `RESOLVE_PAYPAL_SANDBOX_MERCHANT_ID`, `RESOLVE_PAYPAL_RESOLVE_MERCHANT_ID`; explicit read/refund enablement, optional webhook ID. Already present for the authorized isolated run. Keep global production defaults disabled until deliberately configured. |
| Merchant PayPal identity | `RESOLVE_PAYPAL_LOGIN_CLIENT_ID`, `RESOLVE_PAYPAL_LOGIN_CLIENT_SECRET`, `RESOLVE_MERCHANT_WEB_ORIGIN`; explicit login enablement and registered callback. |
| Google | `RESOLVE_GOOGLE_CLIENT_ID`, `RESOLVE_GOOGLE_CLIENT_SECRET`, `RESOLVE_CUSTOMER_PUBLIC_ORIGIN`; explicit Google enablement and registered callback. |
| Shopify | `RESOLVE_SHOPIFY_SHOP_DOMAIN`, `RESOLVE_SHOPIFY_ADMIN_TOKEN`, `RESOLVE_RESOLUTION_CONNECTOR_MERCHANT_ID`. |
| EasyPost | `RESOLVE_EASYPOST_API_KEY`, `RESOLVE_RESOLUTION_CONNECTOR_MERCHANT_ID`. |
| Zendesk | `RESOLVE_ZENDESK_SUBDOMAIN`, `RESOLVE_ZENDESK_OAUTH_TOKEN`, `RESOLVE_HELPDESK_MERCHANT_ID`; signed webhook secret where enabled. |
| Resend | `RESOLVE_RESEND_API_KEY`, `RESOLVE_RESEND_FROM`, `RESOLVE_CUSTOMER_SIGNING_KEY`, `RESOLVE_CUSTOMER_EMAIL_MERCHANT_ID`, `RESOLVE_CUSTOMER_PUBLIC_ORIGIN`; enabled email transport. |
| SMTP | `RESOLVE_SMTP_HOST`, `RESOLVE_SMTP_PORT`, `RESOLVE_SMTP_USER`, `RESOLVE_SMTP_PASSWORD`, `RESOLVE_SMTP_FROM`, signing/merchant/public-origin values above; Node mailer installed. |
| AI | `RESOLVE_AI_GROQ_KEY`, `RESOLVE_AI_OPENROUTER_KEY`; enabled mode, selected supported models and budget; see `backend/ai-env.example.ps1`. |
| Resolve SDK | `RESOLVE_API_URL`, `RESOLVE_API_KEY`, stable `RESOLVE_APP_SOURCE`; support methods additionally need explicitly granted source-bound support access. |
| Deployment | `RENDER_API_KEY` only in the deployment environment if using its API; repository permission, billing review and deployment origins. PostgreSQL `RESOLVE_DATABASE_URL`; preserve `RESOLVE_PLATFORM_ENCRYPTION_KEY` privately. |

Presence is not credential validity. The probe records names/booleans only. Raw response bodies, cookies, bearer credentials, buyer identity and resource references are not included here.

## Actual execution flow and persistence

Explicit owner approval → existing Node SandboxPayPal adapter → official order create → first-party SDK → FastAPI commerce registration → disposable SQLite. Buyer privately approves on PayPal → independent order read validates seller/USD 1.00 → same adapter captures with a stable request ID → SDK revision update. Normal backend case/promise → actual capture/history reads → state-fingerprinted refund approval → separate execution with a stable identity → official refund POST → independent refund/history reads → transaction/audit → merchant and buyer UI. Final SDK revision 3 records the observed fully refunded state.

The initial audit wrapper used `capture_id` instead of the SDK contract's `paypal_capture_id`; the SDK's allowlist omitted that unknown field. The corrected final revision explicitly includes the correct capture ID. The same order is attached to the actual resolution case through the SDK's existing `syncCommerceOrder` method; read-back verifies the link and payment fields. No SDK contract was changed or relaxed.

That complete order/case journey exposed stale SDK freshness after unchanged history refreshes: deduplicated observations retained old timestamps. The promise projection now uses the independently current history check time when available. Controlled aged-observation and actual connected buyer journey checks verify the correction. The actual journey reports sent-to-original-method, not bank receipt.

Private resumable identities/database are under ignored `.local/integration-audit/real-sandbox/`. `real_sandbox_workflow.py create` reuses its single saved order; capture reads before submitting; `real_sandbox_refund.py` persists request/execution identities before any retry. It is a purpose-limited audit runner, not an unattended production payment tool. Do not remove its state and rerun writes without fresh authorization.

## Error evidence

| Scenario | Environment / result | Meaning |
|---|---|---|
| Invalid bearer token | Official Sandbox GET: 401 | Actual provider rejected invalid authentication. |
| Unapproved order | Official order read: PAYER_ACTION_REQUIRED, later APPROVED | No capture was attempted before approval. |
| Provider timeout/429/5xx/invalid JSON/wrong amount/seller/refund parent | Controlled TLS stand-ins and isolated tests | Checks caller errors, recovery and persistence; does not establish real service outage behavior or account rate-limit policy. |
| Unauthorized/invalid/malformed application requests | All 175 operations × three negative vectors | Sanitized status/contract coverage; not complete business-path coverage. See endpoint-coverage.md. |
| Hosted failure/recovery | UNTESTED | Needs deployed staging/production acceptance with authorized credentials. |

Only safe method, route template, status, timestamp and assertion outcomes are publishable. Private diagnostic bodies stay ignored and must be reviewed before sharing. No arbitrary raw backend/provider exception is used as a success response.
