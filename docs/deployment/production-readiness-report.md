# Production readiness assessment

Assessment date: 11 November 2026. **Status: NOT approved for production acceptance; local fixes and the authorized real Sandbox flow are verified, hosted rollout remains blocked.** This is not a penetration-test certification, availability guarantee or authorization to move live money. Product demo/fake success modes have been retired.

## Verified implementation

| Area | Evidence / finding |
|---|---|
| Secrets | Settings use SecretStr; local dotenv/database files are excluded by component ignores. Provider credentials are encrypted at rest; access/session tokens are hashed. No configured secrets/customer evidence were exported into the new documentation. Render secret values are absent from the Blueprint. |
| Merchant authentication | Staff scrypt passwords, durable eight-hour sessions, revocation and DB-backed authentication throttling; legacy key and optional linked PayPal login remain separate. Credential forms use POST and hydration guards. |
| Buyer isolation | Expiring/revocable capabilities and separate customer cookies; buyer requests cannot access merchant APIs. Private links are credentials and must be protected. |
| Authorization | Backend ownership/role checks; restricted SDK grants and app-source binding. Tests cover cross-tenant denial, role changes and guarded financial actions. |
| Financial safeguards | Decimal/cents precision, duplicate prevention, shared capture balances, pending/failed refunds, current acceptance/condition gates, approval expiry and uncertain-outcome recovery are covered by backend/simulation checks. The financial implementation remains Sandbox only. |
| Browser/API boundary | Same-origin gateways enforce exact Origin and body limits. No wildcard CORS enabled. Cookies become Secure on configured HTTPS; hosted proxy/cookie behavior still requires account-backed validation. |
| Input/files | Pydantic schemas, length/shape restrictions, bounded request/provider bodies, scoped attachments and saved PDF-label controls. Credential validation errors are private and do not reflect submitted credentials. Malware scanning and enterprise content retention are not implemented. |
| HTTP protection | Private API no-store, MIME protection, stricter buyer referrer/robots controls; frontend MIME/referrer/frame headers. Full CSP rollout is not claimed. |
| Database | Checksum-tracked immutable migrations; transactions, bounded connection pool and independent readiness. Disposable PostgreSQL checks passed after starting a fresh audit cluster; owner's hosted storage was not changed. |
| Provider webhook | Public PayPal webhook crash repaired; signature verification precedes persistence. Replay/conflict/reversal behavior passed local TLS simulation. Endpoint uses the configured global app/merchant binding; arbitrary per-workspace PayPal webhook routing is not implemented. |
| Dependencies | npm audits for frontend (including dev), SMTP mailer production, SDK and separate checkout store reported zero known vulnerabilities; pip-audit of 36 installed backend packages also reported none. Results are point-in-time advisory checks, not proof against unknown vulnerabilities. |
| Build/runtime | Compiled isolated Next.js pages and real disposable FastAPI routes were exercised. Development reload is absent from deployment commands. Render schema validation passes. Docker daemon unavailable; no container build claimed. |
| Performance | Lazy case tabs, timeline reuse, retained drafts and late-response rejection pass. Bounded triage batching/grouped complaint queries reduce the measured workload from 428 to 220 SQL statements/20 requests. Four local stages, 1/10/50/100 users, completed 3,220 requests with zero errors. P95 at 100 users was 1.70s. No production/soak capacity claim. |
| Real integration | Explicitly authorized official PayPal Sandbox order, buyer approval, capture and full refund independently verified; one persisted refund, zero remaining, actual SDK and merchant/buyer UI values match. Other account-backed services are blocked, not promoted to VERIFIED by mocks. See ../testing/production-integration-report.md. |
| Truthful provider state | Public customer amounts are nullable with explicit verification; stale/unverified history is unavailable rather than a confirmed zero. Completion refreshes history read-only; failures never fabricate success or resubmit a payment. |

## Release blockers and material limitations

1. **No Render deployment/account access:** browser access host unavailable, no deployment credentials. Render billing/repository authorization and reviewed source publication remain required. Production URL, API URL, hosted screenshots and deployed user journeys cannot be verified yet.
2. **No production database/backup acceptance:** new local PostgreSQL is verified; managed instance provisioning, TLS/network policy, PITR, retention, capacity and restore drill must be tested in Render. Do not experiment on the owner's connected database.
3. **Optional integrations are not hosted-verified:** PayPal/Google identity consent/callbacks, signed delivery, Resend/SMTP sender/delivery, Zendesk/Shopify/EasyPost scopes and AI data policy need authorized account-backed checks. The fresh official Sandbox transaction verifies only its documented local scope, not production or every provider action. Exact missing names/present-but-unverified credentials are listed in the integration report.
4. **Account lifecycle limits:** no MFA, email-verification requirement, password reset/recovery, cross-workspace staff membership or self-service provider OAuth installation. Decide whether these meet the intended public audience before opening unrestricted signup. An administrator must own access recovery.
5. **Abuse/operations controls:** auth throttles exist, but service-wide edge WAF/rate limiting, quotas, alert delivery and incident response are not provisioned. Configure edge and service monitoring before broad public access. Do not trust arbitrary forwarded client-IP headers to bypass per-peer throttles.
6. **Financial operations limits:** no live PayPal refunds, bank receipt verification, automatic dispute submission or purchased return labels. Never describe the demonstration as handling live funds. Pause recovery/follow-up workers and reconcile ambiguous provider state when rolling back.
7. **QA scope:** Chromium at four widths, six targeted Firefox checks, all 175 operations' negative probes, 172 operations' successful pytest observations and bounded local load do not prove Safari, full Firefox, accessibility compliance, physical-device behavior, production high concurrency or every possible state permutation. Three positive callback/unlink ledger gaps remain explicit. The test report identifies all unperformed scopes.
8. **Storage/privacy:** database-backed attachments increase DB/backups and need retention/access processes. Exported dispute snapshots can contain private evidence. Define legal/business retention and support policies for the actual operating organization before collecting customers' records.

## Operating requirements

Assign an owner for uptime checks on `/ready`, 5xx/latency alerts, database connections/storage, worker crashes/queue age, secrets rotation, backups and incident response. Store the Fernet key with private backups. Use a synthetic staging workspace and separate Sandbox integration for release tests. Restrict signup until onboarding/support and abuse controls are ready. Keep tokens, private fragments and provider/customer payloads out of external telemetry.

Use `deployment-guide.md` for release and rollback. This audit supplies the files and verified local evidence; Render's account-side validation and acceptance are the next release gate.
