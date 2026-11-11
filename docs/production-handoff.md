# Resolve release handoff

Updated 12 November 2026. **Local code/test/documentation work is delivered for the recorded scope. Production acceptance remains BLOCKED: no deployed website/API URL is available.** Product demo modes are retired. An authorized actual USD 1.00 official PayPal Sandbox order/capture/full-refund workflow is independently verified. The separate hackathon film records one additional authorized USD 8.00 catalogue purchase and completed full refund.

| Phase | Result | Intervention / next step |
|---|---|---|
| 1. Audit | Existing Next.js/FastAPI architecture, roles, forms, SQL, routes, providers/config/startup inventoried; 175 FastAPI operations | [Inventory](testing/application-inventory.md); source inventory is not runtime proof |
| 2. Page/workflow QA | 84 route/mode × four-width observations; combined 32 distinct Chromium checks and six targeted Firefox executions pass | Hosted, physical-device, full Safari/Firefox and accessibility checks remain unperformed |
| 3. Fixes/performance | Demo/fake paths removed; verification totals, post-refund history/gateway and completed-state wording fixed; bounded inbox/dashboard query reduction | [Bug fixes](testing/bug-fix-report.md); production SLO/soak/write-load sizing remains |
| 4. Security/readiness | Auth/tenant/role/input/SQL/XSS/Origin, secret-redaction, dependency, readiness and financial checks | [Assessment](deployment/production-readiness-report.md); recovery/abuse/monitoring/backup policy and hosted acceptance remain |
| 5. Render deployment | Blueprint, startup/env, migrations, HTTPS/callback and rollback guidance prepared | BLOCKED: Render account/repository access, reviewed published source and billing authorization; no commit/push |
| 6. User manual | 51-page PDF, editable source, page/role/tutorial/error guidance and implementation-specific SDK section | [PDF](user-manual/user-manual.pdf), [source](user-manual/user-manual.md), [SDK guide](user-manual/sdk-integration-guide.md) |
| 7. Screenshots | 99 actual local PNGs with captions/hashes; five show real official Sandbox evidence | [Index](user-manual/screenshots/README.md); deployed captures blocked until deployment |
| 8. Narrated videos | **2:57 submission film**, 1080p/30fps: why Resolve exists, real typing/SDK/PayPal workflow and actual automatic investigation. Ten local voiceovers, captions, thumbnail and no-music edition; earlier videos preserved | [Final local package](../PayPal_Resolve_Demo/Production_Report.txt), [source and verification](../video-production/README.md); owner uploads to YouTube; no publication performed |
| 9. Delivery | Organized documentation/archive and code in the existing working tree; decisions in CHG-056 | Prior dirty changes preserved; archive is documentation, not a source publication |
| 10. Extended testing | 1,005 backend passes; 175 operations negative-probed, 172 positive-observed; PostgreSQL, controlled failures, SDK, browser and load evidence | [Tests](testing/testing-report.md), [endpoint ledger](testing/endpoint-coverage.md), [integration status](testing/production-integration-report.md); three positive callback/unlink pytest-ledger gaps explicit |

## Verified scope

- Original release backend: **1,005 passed, 63 opt-in skipped**; CHG-060's subsequent bounded investigation-cache fix: **1,008 passed, 63 skipped**, with **41 targeted passes**. Earlier actual disposable PostgreSQL: **12 dedicated + 98 expanded passes, one opt-in skip**; not reclassified as a new PostgreSQL run.
- Actual Groq-backed automatic investigation of the filmed completed Sandbox order: three linked official provider findings, validated full refund/no-action result, one audited current-owned snapshot read, zero financial writes. Original redundant-read stops are retained. OpenRouter escalation, all-case model quality and hosted AI operation remain unverified. [Evidence](../video-production/research/investigation-evidence.json).
- Controlled provider regression: **49 passed**, **380 mocked HTTP requests, zero pass-through**. Broad browser checks plus successful affected-file retest, separate Google/platform/docs and six Firefox checks are scoped individually; original failures/root causes remain in the report.
- Packaged first-party SDK: **8 passed, three opt-in skipped**; regenerated types/build and frontend TypeScript/docs freshness pass. Fresh npm/pip advisory audits found no known vulnerabilities.
- Local 1/10/50/100-user workload: **3,220 authenticated HTTP requests, zero errors**. Workload SQL statements dropped from 428 to 220 per 20 requests; P95/P99 at 100 users were **1.70s/2.38s**. These are bounded local observations, not production capacity or a controlled speedup claim. [Measurements](testing/performance-report.md).
- Official Sandbox: order creation, private buyer approval, completed capture, independently confirmed COMPLETED full refund of **USD 1.00**; exactly one persisted refund, fulfilled reconciliation and zero remaining. SDK and merchant/buyer amounts match. No live payment, shipment, paid model call or delivered email was initiated.
- PDF: 51 nonempty pages, 32 embedded actual UI images, source snippets and embedded fonts; all pages rendered and visually reviewed. Original 99 PNGs/captions/hashes are supplied. No generated UI image or provider-mock screenshot is in the active manual set.

## Owner actions needed

1. Review the complete working-tree diff. Explicitly authorize a commit/push or publish reviewed source yourself. AGENTS.md prohibits an inferred commit; Render cannot deploy uncommitted local files.
2. Connect the source repository in Render through the secure account/environment flow; `RENDER_API_KEY` is absent. Review recurring costs for six services plus PostgreSQL before authorizing provisioning.
3. Apply the Blueprint with a new managed database and stable encryption key, set exact HTTPS origins, verify `/ready`, then enable only intended workers/integrations. [Deployment and rollback](deployment/deployment-guide.md).
4. Supply missing optional credentials and approved recipients/accounts/budgets through backend/host secret controls. [Exact names and present-but-unverified values](testing/production-integration-report.md). Never send secrets in chat, source or recordings.
5. Complete hosted auth/callback/webhook/delivery, Secure cookies, DNS/TLS, backup restore, monitoring, rollback and realistic load acceptance. Record actual website/API URLs and capture that deployed release. Local/Sandbox evidence does not satisfy those gates.

## Repeatable checks

From `backend`: `uv run python scripts/isolated.py -m pytest -q --audit-output ../.local/integration-audit/backend-release-endpoints.json`.

With a disposable PostgreSQL cluster on loopback 56441 (user `resolve_synthetic`), use `uv run python scripts/isolated.py --postgres-audit --storage-postgres -m pytest tests/test_customer_portal.py tests/test_refund_approvals.py tests/test_assurance.py tests/test_reconciliation.py tests/test_inbox_scaling.py tests/test_platform_operations.py tests/test_api_read_surfaces.py -q`. Run `tests/test_postgres.py` separately without `--storage-postgres` for dedicated migration/import/pool/concurrency checks. Never target production/owner storage.

From `frontend`: `npx playwright test --config playwright.audit.config.ts`. Set `RESOLVE_CAPTURE_MANUAL=1` only for provider-disabled captures. Set `RESOLVE_AUDIT_BROWSER=firefox` for `browser-boundaries.spec.ts promise-health.spec.ts`. For platform set `RESOLVE_UI_PRODUCTION_TEST=1` and run `npx playwright test --config playwright.platform.config.ts`; docs use `playwright.docs.config.ts`.

Repository Postman simulations use `--proxy --lift` with isolated backend flags `--paypal-simulation --followup-simulation`, or browser scenario `RESOLVE_AUDIT_SCENARIO=paypal-email`/`google`. These enable controlled tests, not real-service verification. The capture guard excludes those scenarios from the manual.

From repository root: `npm --prefix sdk/typescript test`; `uv run --with httpx --with psutil python scripts/run_load_audit.py`; `uv run python scripts/audit_inventory.py`; `uv run --with pillow python scripts/screenshot_manifest.py`; `uv run --with reportlab --with pypdf --with pillow python scripts/build_user_manual.py`. PDF tooling needs Segoe UI/Consolas or DejaVu fonts, plus rendering/visual review.

The purpose-limited actual Sandbox state is private, ignored and resumable. Do not delete/reuse it to initiate another order/refund without fresh authorization. Read-only observation does not authorize additional writes.
