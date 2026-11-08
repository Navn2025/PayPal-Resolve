import assert from "node:assert/strict";
import { randomBytes } from "node:crypto";
import { readFile } from "node:fs/promises";
import { Pool } from "pg";

const baseTables = `
CREATE TABLE public.users (
  id text PRIMARY KEY, name text, email text, phone text, password_hash text
);
CREATE TABLE public.orders (
  id text PRIMARY KEY, evidence_revision bigint NOT NULL, status text, user_id text
);
CREATE TABLE public.payments (
  order_id text, provider text, paypal_order_id text, paypal_capture_id text,
  currency text, status text, captured_amount numeric(12,2), refunded_amount numeric(12,2)
);
CREATE TABLE public.products (id text PRIMARY KEY, name text, sku text);
CREATE TABLE public.order_items (
  id int PRIMARY KEY, order_id text, product_id text, quantity int, unit_amount numeric(12,2)
);
INSERT INTO public.users VALUES ('USER-42', 'Test Customer', 'buyer@example.test', '+15550102042', 'never-export-password');
INSERT INTO public.orders VALUES ('STORE-2042', 1, 'shipped', 'USER-42');
INSERT INTO public.payments VALUES
  ('STORE-2042', 'paypal', 'SIMORDERSIMHSDKCOMMERCE', 'SIMHSDKCOMMERCE', 'USD', 'completed', 100.00, 0.00);
INSERT INTO public.products VALUES ('SKU-42', 'Desk lamp', 'LAMP-01');
INSERT INTO public.order_items VALUES (1, 'STORE-2042', 'SKU-42', 2, 50.00);
`;

export async function appDatabase(t, adminUrl) {
  const url = new URL(adminUrl);
  assert.ok(["127.0.0.1", "localhost"].includes(url.hostname), "Use a disposable loopback PostgreSQL cluster.");
  const suffix = randomBytes(6).toString("hex");
  const database = "resolve_sdk_app_" + suffix;
  const role = "resolve_sdk_reader_" + suffix;
  const admin = new Pool({ connectionString: url.href });
  let owner, reader, groupCreated, databaseCreated, roleCreated;
  t.after(async () => {
    await reader?.end();
    await owner?.end();
    try {
      if (databaseCreated) await admin.query("DROP DATABASE " + database);
      if (roleCreated) await admin.query("DROP ROLE " + role);
      if (groupCreated) await admin.query("DROP ROLE resolve_evidence_reader");
    } finally {
      await admin.end();
    }
  });
  await admin.query("CREATE DATABASE " + database);
  databaseCreated = true;
  url.pathname = "/" + database;
  owner = new Pool({ connectionString: url.href });
  await owner.query(baseTables);
  await owner.query(await readFile(new URL("../examples/postgres-views.sql", import.meta.url), "utf8"));
  groupCreated = true;
  await admin.query("CREATE ROLE " + role + " LOGIN");
  roleCreated = true;
  await admin.query("GRANT resolve_evidence_reader TO " + role);
  const readUrl = new URL(url);
  readUrl.username = role;
  readUrl.password = "";
  reader = new Pool({ connectionString: readUrl.href, statement_timeout: 5_000 });
  return { owner, reader, readUrl: readUrl.href };
}
