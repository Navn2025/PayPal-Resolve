# Resolve deployment guide

Prepared 11 November 2026. Target: Render. **Deployment status: not deployed by this audit. No production URL or API URL has been verified.** Do not substitute a localhost address for a production URL.

## Recommended architecture

Use the existing Next.js Node service as the public HTTPS website, a FastAPI Python web service as the authenticated API, managed PostgreSQL, and four Python background workers. Keep all services in one region. The browser calls same-origin Next.js gateways; only those gateways call the API. SDK servers can use `/api/sdk`. This preserves the current architecture, session/Origin rules and durable jobs.

`render.yaml` defines six paid application services and one database, with automatic deployment disabled. Review current Render prices and resource sizes in your account before applying it. The chosen smallest paid plans are starting points, not measured production capacity. Render terminates HTTPS. The API is public for signed PayPal webhooks, authenticated SDK/server usage and health checks; database external access is denied by `ipAllowList: []`. The API has no permissive CORS middleware because browser calls use the website origin.

Attachments and PDF labels currently live in the database. No S3/R2 bucket is required. Back up this data and enforce operational storage limits. Moving attachments to object storage would be a separate implementation change.

## Account and source prerequisites

1. Sign in to Render and connect the Git provider containing this repository. The audit could not access the Render browser host and found no Render deployment credentials. Account-backed resource creation was not attempted.
2. Review the complete working-tree diff, including changes that predate this audit. Authorize a commit/push, or publish the reviewed source yourself. Render builds a repository revision; uncommitted local changes cannot be deployed by pretending they are already in Git. This task has made no commit or push.
3. Enable billing if Render requires it and review the recurring charge for all six services and PostgreSQL. An account, repository permission and billing authorization are required before Apply.
4. Create a Blueprint from `render.yaml`. Keep auto-deploy off while configuring and validating the release. Use a new database first; do not point startup at the owner's current hosted database to experiment with migrations.

## Required environment values

Set secrets in Render's environment controls. Never use `NEXT_PUBLIC_` for service credentials and never paste real values into this guide.

| Variable | Set on | Value / rule |
|---|---|---|
| `RESOLVE_DATABASE_URL` | API and every worker | Blueprint internal PostgreSQL connection string. Use provider-supplied TLS settings for external databases. Never expose to frontend. |
| `RESOLVE_PLATFORM_ENCRYPTION_KEY` | Shared `resolve-production` environment group | Blueprint generates one base64-encoded 256-bit key, accepted by Fernet, and shares it with API/workers. Back it up privately. For an existing database, replace it with that database's existing key before saving/reading connections. |
| `RESOLVE_MERCHANT_WEB_ORIGIN` | Frontend, API, all workers | Exact final HTTPS origin, no path/query/fragment. Example shape: `https://your-resolve-web.onrender.com`. This is an example, not an assigned URL. |
| `RESOLVE_CUSTOMER_PUBLIC_ORIGIN` | Frontend, API, workers | Usually the same HTTPS origin; use a separate buyer host only after domain/routing checks. |
| `RESOLVE_BACKEND_URL` | Frontend only | Exact final API HTTPS origin. Example shape: `https://your-resolve-api.onrender.com`. No trailing resource path. |
| `RESOLVE_MERCHANT_SIGNUP_ENABLED` | API | Defaults true. Set false to close public workspace signup after intended onboarding. |

For a manually managed deployment, generate the encryption key locally from `backend`:

```powershell
uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

This prints a new secret for you to store privately; do not record it in logs/screenshots. Never replace an existing key while encrypted provider connections still depend on it.

Render ignores `sync: false` inside environment groups. The Blueprint therefore prompts for origins directly on the frontend/API and generates the encryption key once in the group. Before enabling email/OAuth, also add the final public origins to the shared environment group so all workers receive them. Do not regenerate the group key during a redeploy.

All optional provider writes, email, Google/PayPal sign-in, automatic reads and AI start disabled in the Blueprint. Per-workspace encrypted connections can enable Sandbox operations separately, so review those records before starting workers against imported data. The root inventory lists every settings variable by name; `backend/.env.example` and `backend/ai-env.example.ps1` explain optional combinations. AI settings come from process environment, not the ordinary dotenv loader.

The local owner-authorized USD 1.00 official PayPal Sandbox workflow is now
verified through actual creation, buyer approval, capture, full refund, database
and UI read-back. It is not a Render verification or permission to enable live
payments. [Integration status and exact missing configuration names](../testing/production-integration-report.md)
separate that result from identity callbacks, delivery, carrier/helpdesk/store
accounts and AI calls that remain blocked. Retain the default-disabled deployment
settings until the intended account-specific acceptance run is prepared.

## Build and start

The Blueprint uses locked dependencies and native runtimes; Docker is unnecessary. Docker Desktop's Linux engine was unavailable during this audit, so no container build is claimed.

| Service | Working directory | Build | Start |
|---|---|---|---|
| Frontend | `frontend` | `npm ci && npm run build` | `npm run start:hosted -- --port $PORT` |
| API | `backend` | `pip install uv==0.10.8 && uv sync --locked --no-dev` | `uv run --no-sync uvicorn app.main:app --host 0.0.0.0 --port $PORT --no-access-log` |
| Operations worker | `backend` | Same Python build | `uv run --no-sync python -m app.operations_worker --loop` |
| Investigations worker | `backend` | Same Python build | `uv run --no-sync python -m app.investigation_worker --loop` |
| Follow-up worker | `backend` | Same Python build | `uv run --no-sync python -m app.followup_worker --loop` |
| Refund recovery worker | `backend` | Same Python build | `uv run --no-sync python -m app.worker --loop` |

`$PORT` above is expanded by Render's Linux shell, not a literal Windows variable. Python is pinned to 3.12.12 and Node to major 22 in the Blueprint. Confirm runtime availability during Render validation. Build exports public guides and OpenAPI downloads before compiling Next.js. Build commands must run with the complete repository available because docs export reads `postman/contracts` outside `frontend`.

The follow-up worker defaults to Resend and needs no Node mailer. SMTP mode additionally requires Node plus `npm ci --prefix backend/mailer` in that worker's runtime; the default Blueprint does not enable SMTP. Configure and validate that runtime separately before selecting SMTP.

## Database and migrations

API startup and workers apply the existing checksum-tracked migrations. SQLite has 028; PostgreSQL has 019. No schema migration was added for this audit. First deploy the API against a new empty PostgreSQL database, inspect startup and `/ready`, then start workers. Use managed backups/PITR before any later release.

For existing data, follow `docs/POSTGRES_MIGRATION.md`: use a read-only source snapshot, import into an empty disposable PostgreSQL schema, verify balances/ownership/counts, then schedule the real cutover. Do not run an unreviewed importer against the owner's configured storage. Never rewrite numbered migration SQL or stored checksums.

## Domains, callbacks and connectivity

1. Record the actual Render-generated website and API URLs in your private release record. Set the exact origins above, then redeploy both services.
2. If using a custom domain, add it in Render, configure its supplied DNS records and wait for certificate verification. Update exact origins and restart all services after changing hosts.
3. Keep frontend-to-API connectivity on HTTPS. `RESOLVE_BACKEND_ALLOW_PRIVATE_HTTP` is only for a deliberately private network; do not enable it to make an insecure public URL work.
4. Register optional merchant PayPal callback `/api/auth/paypal/callback` on the website origin, buyer Google callback `/api/customer-account/google/callback` on the buyer origin, and signed Zendesk callback `/webhooks/zendesk/MERCHANT_UUID` on the frontend. Register PayPal payment webhooks against the backend route from its contract. Never enable optional login merely because an environment field exists.

## Release verification

Use a synthetic workspace and a separate Sandbox account for provider checks. Keep real customer data out of recording artifacts.

- API `/health` must return 200 (liveness); `/ready` must return 200 only when database access works. Test a controlled database outage in staging: `/ready` must return 503 without connection details.
- Open every route in `docs/testing/application-inventory.md`; inspect desktop, tablet and mobile. Download both public documentation resources.
- Create workspace, sign out/in, check Secure/HttpOnly/SameSite cookies over HTTPS, test wrong Origin, expired/revoked credentials, denied staff writes, and tenant isolation.
- Create a case/promise, revise it, add evidence, share/revoke a buyer link, exchange synthetic messages, accept an offer, test return/label workflow, export reviewed evidence, sync and search an order, then refresh to verify persistence.
- Check worker logs/queue age and confirm only expected synthetic tasks run. Email requires a verified sender and a real delivery test. OAuth requires provider-registered callbacks and actual account consent. Test a full separate approval/submission/recovery flow only in PayPal Sandbox after explicit write enablement.
- Run the screenshot suite against the deployed release using an appropriate synthetic fixture/hosted configuration; never run the local fixture seeder against production customer storage. Replace local manual screenshots only with verified hosted screenshots and update their manifest.
- Configure uptime checks on `/ready`, service error/latency alerts, PostgreSQL connection/storage alerts, queue-age alerts, and tested backup restoration. Scrub tokens, URL fragments, provider responses, customer evidence and contacts from external logs.

## Rollback

1. Disable public traffic or serve a maintenance response when financial state is uncertain. Pause workers before rollback; preserve queued jobs, leases, provider request IDs and uncertain outcomes.
2. Redeploy the last verified Git revision for frontend, API and all workers using Render's deployment controls. Keep environment secrets and encryption key unchanged. Verify database compatibility before starting older code.
3. Do not delete migration history or run a destructive down-migration. This audit adds no migration; future releases may need a forward repair. For a destructive database incident, restore a managed backup to a NEW database and reconcile subsequent events/provider state before switching.
4. Run `/ready`, authentication, owned-case reads, SDK connectivity and worker checks. Reconcile pending/uncertain refunds from provider evidence before allowing another execution. An application rollback cannot reverse an already submitted refund.

## Authoritative references

- [Render Blueprint specification](https://render.com/docs/blueprint-spec)
- [Render background workers](https://render.com/docs/background-workers)
- [Render deployment behavior](https://render.com/docs/deploys)
- [Next.js self hosting](https://nextjs.org/docs/app/guides/self-hosting)
- [FastAPI deployment](https://fastapi.tiangolo.com/deployment/docker/)

Provider-side Blueprint validation, resource provisioning, hosted callback checks, production load tests and rollback drills remain unperformed until account/source access is available.
