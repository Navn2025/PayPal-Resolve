import { Pool } from "pg";
import { ResolveClient } from "@resolve-paypal/sdk";

const { RESOLVE_API_URL, RESOLVE_API_KEY, APP_EVIDENCE_DATABASE_URL } = process.env;
const order = process.argv[2];
if (!RESOLVE_API_URL || !RESOLVE_API_KEY || !APP_EVIDENCE_DATABASE_URL || !order) {
  throw new Error("Set RESOLVE_API_URL, RESOLVE_API_KEY and APP_EVIDENCE_DATABASE_URL; pass an app order ID.");
}
const pool = new Pool({
  connectionString: APP_EVIDENCE_DATABASE_URL,
  connectionTimeoutMillis: 5_000,
  statement_timeout: 5_000,
});
try {
  const resolve = new ResolveClient({ baseUrl: RESOLVE_API_URL, apiKey: RESOLVE_API_KEY, timeoutMs: 30_000 });
  const evidence = resolve.connectPostgres(pool, { source: "my-store" });
  const report = await evidence.inspect(order);
  console.log(JSON.stringify({
    caseId: report.case_id,
    status: report.status,
    lastCheckedAt: report.last_checked_at,
    checks: report.checks.map(({ field, status }) => ({ field, status })),
  }, null, 2));
} finally {
  await pool.end();
}
