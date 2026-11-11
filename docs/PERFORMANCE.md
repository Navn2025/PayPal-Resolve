# Responsive local preview and case loading

CHG-051, 2026-11-10.

## Run the optimized local app

Start the API from `backend`:

```powershell
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In another terminal at the repository root:

```powershell
npm --prefix frontend run build:preview
npm --prefix frontend run preview
```

Open http://127.0.0.1:3000/workspace. The compiled preview uses `.next-preview`
and the existing local frontend configuration. The script binds loopback only;
it does not publish the website. Stop any frontend already using port 3000 first.
Source/configuration changes require rebuilding and restarting this preview.
Use `npm run dev` inside frontend for automatic rebuilds while editing.

## What changed

- Case details appear before their linked payment requests complete. Until the
  current payment and reconciliation are available, financial controls remain
  ineligible. Backend approval/submission checks remain authoritative.
- The evidence timeline loads on first visit and is reused within that case.
  Changing cases or refreshing details invalidates that local timeline. Late
  responses from a previously selected case cannot replace the current detail.
- Closed offers/returns/packages, return guides, dispute tools, Zendesk and
  investigations no longer all fetch immediately. The original connected-app
  request still loads in the overview. Investigations stop polling when closed.
- The customer tab loads independent reads together and retains its mounted state
  when switching tabs in the same case, preserving an unfinished heading draft.
  Use its refresh action for newly arrived messages. Changing cases resets state.
- Operations loads identity once per mount and runs each tab's independent reads
  together. Obsolete responses cannot overwrite the newly selected tab's state.
- Narrow merchant layouts wrap the header/actions and let the case tab strip
  scroll locally, rather than widening the whole page.
- PostgreSQL reuses connections through psycopg-pool 3.3.3: lazy opening, maximum
  eight connections per process/store, at most 32 queued borrowers, an eight-second
  checkout deadline, 60-second excess-idle and ten-minute lifetime limits. No
  financial operation is automatically replayed after a connection failure.
  Broken connections are discarded; transaction-local schema/read settings reset
  and the API closes resources at shutdown. Reads retain repeatable-read/read-only
  isolation; write locks and transaction boundaries remain.
- Authenticated browser reads resolve identity once per request, using the same
  transaction for legacy/staff fallback and a joined merchant lookup. Writes
  recheck the current session at the authorization gate. Sessions, roles and
  financial results are not cached across requests.

## Evidence and limits

A read-only `SELECT 1` against the configured hosted PostgreSQL database took
3.330, 3.359 and 3.182 seconds with fresh connections. After pooling and combining
read setup, the cold read took 2.939 seconds; warm reads took 1.211 and 1.182 seconds.
These are local connectivity measurements, not whole-page or provider timings.
Network distance still affects hosted database reads.

The CHG-051 isolated production browser check observed five distinct initial API paths
for a simple case, no unopened secondary-panel requests, one timeline request
across a return visit and no customer-panel refetch on a tab return. It checked
rapid case changes and a 390px viewport. The complete merchant/buyer workflow also
passed against this compiled build. Synthetic SQLite/PostgreSQL tests verify
rollback, pooled connection reuse, read-only/schema isolation, broken connection
recovery and permission revocation. See the engineering log for exact commands,
counts and unsupported SQLite-specific fixtures in the exploratory PostgreSQL run.

Run the compiled synthetic browser checks from frontend with:

```powershell
$env:RESOLVE_UI_PRODUCTION_TEST='1'
npx playwright test -c playwright.platform.config.ts
```

This builds a disposable source copy without owner dotenv files and starts its
own synthetic API. Development Strict Mode may make duplicate effect calls;
the production check measures the compiled path used by the local preview.

No migrations, API payloads, provider behavior or financial permissions changed.
The application has not been deployed or load-tested at production traffic scale.
The pool bounds apply per process, so size the total deployment's connection budget
before increasing worker/replica counts.

Pool lifecycle follows the [Psycopg connection pool documentation](https://www.psycopg.org/psycopg3/docs/advanced/pool.html).

After merge repair CHG-053, the initial case check observes eight distinct API
paths: the incoming promise-health, next-action and inbox-risk reads add three
paths. Unopened secondary panels remain deferred; timeline reuse, draft retention
and mobile overflow checks still pass. The new layout's recent-activity area
invites opening the evidence timeline until those events have been loaded.

## CHG-056 bounded load and query reduction

The current inbox batches operations/message-count/intake reads for at most 100
cases at a time, within the same transaction. The dashboard groups complaint
categories once. No session, role, approval or financial result is cached across
requests. A 105-case test checks query growth, filtered pagination totals and
equality with ordinary projections; SQLite and actual PostgreSQL checks pass.

The five-route local workload now issues 220 SQL statements per 20 requests,
versus 428 before this change. At 1/10/50/100 closed-loop users, all 3,220 final
requests returned 200. Measured P95 values were 9.086/97.620/820.103/1702.320ms.
Host activity differed between runs; these are bounded local observations, not
a controlled speedup percentage or production capacity. See
[full workload, CPU/RSS and limitations](testing/performance-report.md).
