# Application testing report

**12 November follow-up, CHG-060:** the actual automatic investigation exposed a
false stop when a model selected an already-current owned provider fact. The
bounded verified-snapshot cache fix passed **41 targeted tests** and the full
isolated backend **1,008 passed / 63 opt-in skipped**, with one existing
Starlette/httpx deprecation warning. Real Groq120B retest finished with three
official Sandbox findings and no financial writes. Earlier blocked attempts and
the changed test expectation are preserved in the engineering log and film
evidence; this does not replace the earlier audit's separately scoped totals.

Evidence date: 11 November 2026. **Local release work is verified for the specified scope; production deployment and full acceptance remain blocked.** Product demo/fake-success modes are removed. Tests use real application code and disposable databases. Official PayPal Sandbox evidence is separate from controlled provider failures. No claim covers every possible input/state, browser, device or production condition.

## Final execution summary

The table counts explicitly named test units, not product capabilities. Rows overlap (for example user workflows are frontend checks and security tests are also in the backend suite); do not sum rows into an invented global total. Opt-in skips are not automatically failures or credential blockers.

| Category | Total tests | Passed | Failed after retest | Blocked | Skipped / untested in that suite |
|---|---:|---:|---:|---:|---:|
| Backend APIs / logic, isolated SQLite | 1068 | 1005 | 0 | 0 | 63 opt-in |
| Database, actual loopback PostgreSQL (dedicated + expanded) | 111 | 110 | 0 | 0 | 1 opt-in |
| SDK, packaged Node client | 11 | 8 | 0 | 0 | 3 opt-in |
| Frontend, distinct Chromium checks | 32 | 32 | 0 | 0 | 0 in combined scenarios |
| User workflows, main Chromium suite (subset above) | 29 | 29 | 0 | 0 | 0 after separate Google run |
| Security, dedicated auth/readiness/security files (backend subset) | 40 | 39 | 0 | 0 | 1 |
| Performance, bounded local stages | 4 | 4 | 0 | 0 | Production / soak not run |
| Responsive UI, route/mode × viewport observations | 84 | 84 | 0 | 0 | Hosted / physical-device sweep not run |
| Firefox, additional targeted engine executions | 6 | 6 | 0 | 0 | Full Firefox/Safari suite not run |

- Final full backend: **1,005 passed, 63 skipped**, 130.96s. Earlier post-fix full run 1,001 passed; four HTTP surface tests were then added. Dedicated surface retest: **25 passed, 1 opt-in skipped**, 18.34s. Financial approval, amount precision, duplicates, pending/failed/shared balances and acceptance/condition gates remain covered. One upstream Starlette/httpx TestClient deprecation warning remains.
- Actual PostgreSQL: **12 dedicated passes**, then **98 expanded passes / 1 opt-in skip** against fresh per-test schemas (final result verified before handoff). This includes real engine-appropriate audit-write fault triggers, independent app instances, rollback, snapshot/pool/migration fidelity and batched inbox pagination. No owner/hosted database was opened.
- Controlled provider transport: **49 passed**, **380 mocked HTTP requests / zero pass-through**. Real HTTPX/routes/storage are exercised; the upstreams are repository-owned TLS stand-ins. Timeout, 401/403/404/429/5xx, malformed responses, wrong identity/amount/parent, pending/failed/shared capture, uncertain result/retry and signature/replay cases are scoped to those controls.
- Main compiled Chromium: final combined evidence is **29 distinct passing checks**, including separate controlled Google. The broad run passed 27 with one financial display failure; after the gateway fix the complete affected workspace file passed **9/9**, including that failure. Google: **1 pass, four mocked calls, zero pass-through**. Platform: **2 passes**. Public docs: **1 pass** without an API. No unsupported all-green original run is invented.
- Firefox: **6 passes**, covering hostile stored-text escaping, Origin denial, persistent mobile auth/navigation, logout and promise/next-step behavior. These are desktop Firefox emulated viewport checks, not physical-device or full cross-browser certification.
- SDK: **8 passed, 3 opt-in skipped**; type generation/build uses the regenerated contract. TypeScript, docs freshness and locked compiled builds pass. Fresh npm audits for frontend/SDK/shop and production mailer, plus pip-audit of installed backend packages, reported no known vulnerabilities. Advisory snapshots do not establish absence of unknown vulnerabilities.
- Official Sandbox: one explicitly authorized USD 1.00 order → private buyer approval → capture → full refund **VERIFIED**. Independent refund read COMPLETED, database exactly one refund, reconciliation fulfilled, USD 0.00 remaining; real merchant/order/buyer UI assertions and five genuine captures pass. No production funds, mail delivery, paid model call or shipment was used.

## Page-by-page results

“Pass - local” identifies the covered assertions/rendering only. Four widths are 1440 desktop, 1180 laptop, 768 tablet and 390 phone. Forms and interactions are tested separately from the route sweep. Optional credentials and production callbacks remain explicitly blocked.

| Page | Feature | Test Result | Issue Found | Fix Applied |
|---|---|---|---|---|
| `/` | Landing, merchant/buyer/docs links, workflow anchor, responsive layout | Pass - local | None reproduced | None |
| `/login` | No-JS credential protection, invalid/valid key, session cookie, sign-out | Pass - local | Optional callback loading message misleading | BUG-004; controlled identity flow passes |
| `/account` | Sign-in, signup, HTML validation, owner claim/invitation variants | Pass - local form + platform signup/invite | Pre-hydration GET fallback could expose password in URL | BUG-001; POST, disabled hydration controls and busy guard |
| `/demo` | Legacy redirect to real merchant login | Pass - compiled browser | Product sample mode retired | Redirect, no simulated records |
| `/workspace` | Authentication, inbox, nested `?case=UUID`, evidence, promises, deferred panels | Pass - local; desktop/tablet/mobile | Tablet width 793px at 768px | BUG-002 header/icon rail repair |
| `/workspace` case Overview | Promise creation/versioned edits, source notes, manual milestone, payment linking, AI advisory review | Pass - covered local backend/browser checks | Unverified money had misleading confirmed totals | Nullable verification + fresh post-execution history; gates retained |
| `/workspace` case Evidence timeline | Events, tab reuse | Pass - local performance/browser | None reproduced | None; one timeline request across revisits verified |
| `/workspace` case Buyer receipt | Readable receipt, print control and source labels | Pass - local rendering/capture | None reproduced | Actual printer output not tested |
| `/workspace` case Customer portal | Create/revoke private link, two-way messages, privacy and refresh | Pass - local independent buyer session | None reproduced | Existing capability isolation retained |
| `/workspace` case operations | Offer publish/accept, return approval, PDF upload/download, dispute hold/tracing/export review | Pass - platform workflow | No new issue in covered states | Physical shipping/dispute submission remain external |
| `/workspace/orders` | Search registered order, inspect item, create/open case, phone layout | Pass - local API/browser | None reproduced | None |
| `/workspace/settings` | Session view, SDK one-time setup/copy/hide/revoke, optional identity | Pass - default local; controlled optional flows pass | Test assumed PayPal was always disabled; callback status locator ambiguous | Test supports enabled/disabled capability and scopes status; BUG-004 loading copy |
| `/workspace/operations` Overview | Whole-workspace metrics, recorded ledger source labels | Pass - local at 4 widths | None reproduced | None |
| `/workspace/operations` Missed promises | Scan/alerts, copy draft | Pass - platform workflow and rendering | None reproduced | No mail auto-send claimed |
| `/workspace/operations` Support imports | Ticket form, matching UI, private sources | Pass - rendering/local service checks | Account scopes and hosted delivery unverified | No account-backed claim |
| `/workspace/operations` Team | Invitation acceptance, agent denied key administration, role gates | Pass - browser + backend | No MFA/recovery feature exists | Documented as limitation, not hidden |
| `/workspace/operations` Connections | Provider forms, return policy, support key grant | Pass - platform/local | New production provider accounts unavailable | Defaults disabled; hosted checks pending |
| `/workspace/operations` Audit | Actor/event list and narrow layout | Pass - local | None reproduced | Development log kept separate |
| `/customer` | Entry, order intake, evidence upload, own case, revoked-link denial | Pass - local independent browser | None reproduced | Buyer cannot access merchant APIs |
| `/customer?demo=1`, `?intake=1` | Retired query modes cannot create buyer data | Pass - browser | Fake local state removed | Valid private token required |
| `/customer/account` | Disabled state, optional email/Google, own case list, logout | Default + controlled Google/email flows pass; real account/delivery blocked | No public buyer registration/password-reset exists | Manual describes actual methods |
| `/docs` | Search, no results, downloads, mobile guide selection | Public docs source/compiled route sweep pass; dedicated test passes | None reproduced | No backend dependency |
| `/docs/getting-started` | First-case guide, sections/anchors | Pass - 4-width render/capture | None reproduced | None |
| `/docs/merchant-workspace` | Merchant workflow guide | Pass - 4-width render/capture | None reproduced | None |
| `/docs/buyer-portal` | Buyer guide | Pass - 4-width render/capture | None reproduced | None |
| `/docs/returns-and-replacements` | Returns/replacement guide | Pass - 4-width render/capture | None reproduced | None |
| `/docs/refunds-and-disputes` | Refund/dispute guide | Pass - 4-width render/capture | None reproduced | None |
| `/docs/sdk-integration` | SDK guide and copy controls | Pass - 4-width render/capture | None reproduced | SDK server examples are not client secrets |
| `/docs/api-and-reliability` | API contract/recovery guide | Pass - 4-width render/capture | None reproduced | None |
| `/docs/connections` | Optional services guide | Pass - 4-width render/capture | None reproduced | None |
| `/docs/running-resolve` | Setup/settings guide | Pass - 4-width render/capture | None reproduced | None |
| `/docs/troubleshooting` | Error/recovery guide | Pass - 4-width render/capture | None reproduced | None |
| Unknown routes | Not-found page and safe return links | Pass - documentation suite checks 404 | No hidden dashboard found | Not a registration/recovery feature |
| Backend `/health`, `/ready` | Liveness, database probe/failure sanitization, cache headers | Pass - targeted API checks | Liveness alone did not prove DB readiness | OPS-001/002 |
| Backend `/webhooks/paypal/sandbox` | Signed durable intake, duplicate/conflict/reversal handling | Pass - fixed TLS simulation | Undefined merchant on public route | BUG-003 |

## Endpoint execution coverage

All **175** exported FastAPI operations have three negative probes (525 tests). **172** operations also have an observed successful asserted pytest workflow. **3** identity callback/unlink operations lack a positive observation in the pytest ledger; configured browser consent flows supply separate controlled evidence but real account-backed identity remains blocked. [Per-endpoint methods, statuses and test IDs](endpoint-coverage.md) distinguish this precisely. The contract also inventories Next gateways and the separate store API.

Every-operation missing/incorrect/large payload, expired token, duplicate/concurrent write, DB outage and upstream failure combinations have not all been run. Selected high-risk paths have dedicated tests. Do not call this exhaustive state-space coverage.

## Failures, root causes and retests

| Issue / reproduction | Expected / actual | Root cause and fix | Retest |
|---|---|---|---|
| Default promise-health browser expected confirmed $0/$30 without a provider check | Unknown proof must stay unavailable; old expectation failed | Product false-zero display fixed, then regression updated to assert unavailable totals | Six Firefox checks and final Chromium affected tests pass |
| Complete a controlled Sandbox refund, then inspect totals | Fresh verified balances; UI showed unavailable after history invalidation | Completion invalidated the old snapshot; add one read-only history refresh, preserve errors/no duplicate payment; explicit same-origin gateway allowlist route added | Nine workspace checks pass; actual authorized Sandbox merchant/buyer capture pass |
| Open buyer workflow after many earlier browser-created cases | Find the original case; locator waited on page one | Valid pagination moved the QA case beyond 12 rows; test now searches stored records | Final affected suite passes |
| Force the approval suite onto PostgreSQL | Independent restart and real rollback tests; five fixtures failed using SQLite .path | Test fixtures were engine-specific; use independent PostgreSQL store instances and real PostgreSQL trigger faults | Expanded PostgreSQL run passes; no failing case hidden/skipped |
| Search Docs immediately after copying code | No-results state visible; strict locator found two valid status regions | Test scoped to the no-results text instead of assuming one live region | Dedicated compiled docs check passes |
| Fulfilled actual Sandbox case still shows missing due date | Completion should not imply another payment prerequisite | Label record completeness with explicit no-payment note; retain the source detail | Real compiled Sandbox capture/assertion passes |
| Fresh unchanged history but SDK buyer journey says needs checking | A current independent read should refresh verification; individual observation times stayed old | Use the current full-history check timestamp in the promise projection; retain old audit observations | Controlled aged-observation regression and actual connected Sandbox journey pass; full backend/PG/provider retests pass |
| Endpoint recorder saw only top-level route objects | All contract operation observations | FastAPI nested routers; compile templates once from current exported contract, avoiding per-app generation overhead | 175 negative-probed / 172 positive-observed operation ledger |

Earlier CHG-055 credential/native submission, tablet overflow, public webhook NameError and callback-loading fixes remain documented in bug-fix-report.md. Their original failed attempts are preserved in ENGINEERING_LOG.md. A superseded slow instrumentation run was stopped; it is not counted as a product pass/failure. Invalid command/setup attempts (wrong test filename, stopped audit PG path, unsupported pip-audit option) were corrected before final checks.

## Performance evidence

The compiled platform regression still observes eight initial unique API paths, one timeline request across revisits, zero customer-panel refetches on tab return, retained drafts and late-response rejection. [Load report](performance-report.md) measures 1/10/50/100 closed-loop local users and 3,220 real authenticated HTTP requests with zero final errors. The deterministic workload dropped from 428 to 220 SQL statements per 20 requests after batching/grouping. Timings are local observations on an uncontrolled shared host; no production capacity or speedup percentage is claimed.

## Screenshots, errors and untested boundaries

The current directory contains **99 genuine application PNGs** with captions/hashes: 84 route/mode/viewport observations, registration/error/operations/dialog/timeline/receipt captures and five actual official Sandbox result screens. Provider mocks did not feed the manual captures. The **51-page PDF** embeds 32 images and project-specific SDK/code guidance. Poppler rendered all pages; contact sheets and code/workflow details were visually reviewed. No fake generated UI image is included. These are local, not deployed screenshots.

The route sweep records zero JavaScript page exceptions and zero 5xx responses. Expected unauthenticated/invalid-key 401s and handled private-case optional-data 404s are recorded, not described as a silent console. Final sanitized response paths are retained in the local page evidence. See handoff notes for exact final handled-response scope.

Production HTTPS/DNS/cookies, actual OAuth/webhook/email delivery, external SDKs without credentials/consent, managed backup restore, production rollback/load/soak, Safari/WebKit, physical devices, accessibility certification, every button/state permutation and all per-endpoint adversarial vectors remain BLOCKED or UNTESTED as applicable. No shipping initiation, live refund, public password-reset flow, bank-credit proof or direct PayPal dispute submission is invented.

See [real integration status / exact missing names](production-integration-report.md), [readiness](../deployment/production-readiness-report.md) and [release handoff](../production-handoff.md). The owner selected Render; account/source/billing access is still required. No commit/push was made.
