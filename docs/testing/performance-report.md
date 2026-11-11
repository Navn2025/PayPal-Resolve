# Local performance report

11 November 2026. Real loopback FastAPI and a new disposable SQLite database; no provider requests, production traffic or owner data. One Uvicorn process, 20 seeded cases; each closed-loop user cycles five authenticated case list/inbox/dashboard/detail/timeline GETs, 20 requests per user, no think time. These are bounded finite stages, not a soak or realistic browser-session capacity model.

| Concurrent users | Requests | Average ms | P50 ms | P95 ms | P99 ms | Requests/s | Error % | API CPU seconds | Peak RSS MiB | SQL statements |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 20 | 7.478 | 7.597 | 9.086 | 9.104 | 133.588 | 0.0 | 0.188 | 84.7 | 220 |
| 10 | 200 | 62.773 | 61.543 | 97.62 | 129.598 | 156.326 | 0.0 | 9.125 | 90.6 | 2200 |
| 50 | 1000 | 261.912 | 172.857 | 820.103 | 1329.96 | 166.047 | 0.0 | 11.781 | 91.7 | 11000 |
| 100 | 2000 | 553.258 | 387.157 | 1702.32 | 2382.775 | 161.261 | 0.0 | 20.938 | 92.5 | 22000 |

All 3,220 final requests returned 200 with expected JSON object shape. The harness records each latency, server-process CPU/RSS and transaction/statement counts. CPU is summed process time and may exceed one core; database transaction scope includes application work and overlapping concurrent time, not isolated SQL execution latency. No query text or credentials are logged.

## Optimization and limits

The original workload issued 428 statements per 20 requests. Bounded transaction-local triage/message/intake prefetching and one grouped complaint query reduce the same workload to 220. A 105-case test crosses batch boundaries and checks query growth, search/assignment filtering, pagination totals and equality with the ordinary single-case projection. SQLite and real PostgreSQL regressions pass. Tenant/session/approval/financial state is never cached across requests.

Before optimization, the corrected-monitor local observations at 1/10/50/100 users had P95 102.567/900.058/7570.326/14170.922ms with no HTTP errors. That run overlapped other audit work. The first attempt incorrectly monitored the Windows venv launcher (5 MiB, zero CPU); its CPU/memory values are invalid and excluded. The corrected harness selects the actual API PID from its private runtime record and verifies its command line. Before/after host activity differs, so do not quote a speedup percentage or assign the entire latency change to this patch.

At 100 users final P95 is approximately 1.70s, P99 2.38s. This is not evidence of acceptable production tail latency. Higher loads were not attempted on the shared host. Production uses PostgreSQL; no hosted PostgreSQL load, sustained-write load, worker queue stress, multi-region/browser metric, LCP/INP, real-provider latency, leak/soak proof or capacity guarantee is claimed. Define an SLO and repeat on provisioned staging with realistic data/traffic before sizing Render.

## Repeat

From repository root: `uv run --with httpx --with psutil python scripts/run_load_audit.py`. Optional bounds: `--users 1,10,50,100 --requests-per-user 20`. The launcher clears inherited service credentials, uses loopback only, creates its own database and stops only its recorded audit process. Outputs remain under ignored `.local/integration-audit/`; never substitute a production target. No application dependency was added for measurement.
