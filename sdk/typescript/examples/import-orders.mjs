import { Pool } from "pg";
import { ResolveClient } from "@resolve-paypal/sdk";

const {
  RESOLVE_API_URL, RESOLVE_API_KEY, APP_EVIDENCE_DATABASE_URL,
  RESOLVE_IMPORT_AFTER = "", RESOLVE_APP_SOURCE = "my-store",
} = process.env;
if (!RESOLVE_API_URL || !RESOLVE_API_KEY || !APP_EVIDENCE_DATABASE_URL) {
  throw new Error("Set RESOLVE_API_URL, RESOLVE_API_KEY and APP_EVIDENCE_DATABASE_URL on the app server.");
}

const pool = new Pool({
  connectionString: APP_EVIDENCE_DATABASE_URL,
  connectionTimeoutMillis: 5_000,
  statement_timeout: 5_000,
});
let imported = 0;
let after = RESOLVE_IMPORT_AFTER;
try {
  const resolve = new ResolveClient({ baseUrl: RESOLVE_API_URL, apiKey: RESOLVE_API_KEY });
  const orders = resolve.connectPostgres(pool, { source: RESOLVE_APP_SOURCE });
  for await (const order of orders.registerAll({ after })) {
    imported += 1;
    after = order.order_reference;
    console.log(JSON.stringify({ orderReference: after, state: "registered" }));
  }
  console.log(JSON.stringify({ imported }));
} catch (error) {
  console.error(error instanceof Error ? error.message : "Could not register the next order.");
  console.error(JSON.stringify({ imported, resumeAfter: after }));
  process.exitCode = 1;
} finally {
  await pool.end();
}
