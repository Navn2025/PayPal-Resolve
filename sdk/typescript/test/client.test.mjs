import assert from "node:assert/strict";
import { execFileSync, spawn, spawnSync } from "node:child_process";
import { once } from "node:events";
import { mkdtemp, rm } from "node:fs/promises";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createInterface } from "node:readline";
import { test } from "node:test";
import { setTimeout as delay } from "node:timers/promises";
import { fileURLToPath } from "node:url";
import { createResolve, ResolveApiError, ResolveClient, ResolveTransportError, PostgresResolutionConsumer } from "@resolve-paypal/sdk";

const fixtureKey = "rslv_" + "x".repeat(43);

async function fastApi(t, paypalSimulation = false) {
  const backend = fileURLToPath(new URL("../../../backend/", import.meta.url));
  const fixture = fileURLToPath(new URL("./fixture.py", import.meta.url));
  const cleanEnv = { ...Object.fromEntries(Object.entries(process.env).filter(([key]) => !/^RESOLVE_/i.test(key))), RESOLVE_ISOLATED_TEST: "1" };
  const runtime = spawnSync("uv", ["run", "--no-sync", "python", "-c", "import sys; print(sys.executable)"], {
    cwd: backend, encoding: "utf-8", env: cleanEnv, timeout: 25_000, windowsHide: true,
  });
  assert.equal(runtime.status, 0, "Install the backend with uv sync before running the SDK integration test.");
  const scratch = await mkdtemp(join(tmpdir(), "resolve-sdk-"));
  const child = spawn(runtime.stdout.trim(), [fixture, join(scratch, "fixture.sqlite3"), ...(paypalSimulation ? ["--paypal-simulation"] : [])], {
    cwd: backend, env: cleanEnv, stdio: ["ignore", "pipe", "ignore"], windowsHide: true,
  });
  const stopped = new Promise((resolve) => child.once("close", resolve));
  const lines = createInterface({ input: child.stdout });
  t.after(async () => {
    lines.close();
    if (child.exitCode === null && child.signalCode === null) child.kill();
    await stopped;
    await rm(scratch, { recursive: true, force: true });
  });
  const firstLine = await Promise.race([
    once(lines, "line", { signal: AbortSignal.timeout(35_000) }).then(([line]) => line),
    stopped.then(() => { throw new Error("The isolated Resolve test server exited."); }),
  ]);
  const { port, key, otherKey, commerceKey } = JSON.parse(firstLine);
  const baseUrl = `http://127.0.0.1:${port}`;
  const readyDeadline = performance.now() + 30_000;
  while (performance.now() < readyDeadline && child.exitCode === null && child.signalCode === null) {
    const ok = await fetch(baseUrl + "/health", { signal: AbortSignal.timeout(1_000) })
      .then((response) => response.ok).catch(() => false);
    if (ok) return { baseUrl, key, otherKey, commerceKey };
    await delay(200);
  }
  throw new Error("The isolated Resolve test server did not become healthy.");
}

test("packaged client runs a case and private buyer link lifecycle against FastAPI", { timeout: 90_000 }, async (t) => {
  const { baseUrl, key, otherKey } = await fastApi(t);
  const client = new ResolveClient({ baseUrl, apiKey: key });
  const other = new ResolveClient({ baseUrl, apiKey: otherKey });
  assert.equal((await client.getMerchant()).name, "SDK test workspace");
  const created = await client.createCase({ title: "Merchant-only note", order_reference: "ORDER-421" });
  assert.equal((await client.getCase(created.id)).outcome, created.outcome);
  assert.equal((await client.listCases({ limit: 1, offset: 0 })).items[0].id, created.id);
  assert.equal((await client.listCases({ limit: 1, offset: 1 })).items.length, 0);
  assert.equal((await other.listCases()).total, 0);
  assert.equal((await client.getOperationsDashboard()).case_count, 1);
  assert.equal((await other.getOperationsDashboard()).case_count, 0);
  assert.deepEqual((await client.scanMissedPromises()).items, []);
  assert.deepEqual((await client.getMissedPromises()).items, []);
  assert.deepEqual((await client.getReturnWorkflow(created.id)).items, []);
  await assert.rejects(other.getReturnWorkflow(created.id), { status: 404 });
  await assert.rejects(other.getCase(created.id), (error) => error instanceof ResolveApiError && error.status === 404);
  assert.ok(Array.isArray((await client.getCaseTimeline(created.id)).items));
  const investigations = await client.getInvestigations(created.id);
  assert.equal(investigations.items[0].state, "queued");
  await assert.rejects(other.getInvestigations(created.id), { status: 404 });
  await assert.rejects(client.reviewInvestigation(created.id, created.id, {
    expected_revision: investigations.items[0].case_revision,
    evidence_snapshot: "0".repeat(64), decision: "approve",
  }), { status: 404 });

  const link = await client.issueCustomerLink(created.id, { title: "Your return", show_order_reference: true });
  const url = new URL(link.public_url);
  assert.equal(url.origin, "https://resolve.example.test");
  assert.equal(url.pathname, "/customer");
  assert.equal(url.hash.slice(1), link.token);
  const status = await client.getCustomerLink(created.id);
  assert.equal(status.active, true);
  assert.equal("token" in status, false);
  const buyerView = (token) => fetch(baseUrl + "/customer-portal/view", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token }),
  });
  const response = await buyerView(link.token);
  assert.equal(response.status, 200);
  const buyer = await response.json();
  assert.equal(buyer.title, "Your return");
  assert.equal(buyer.order_reference, "ORDER-421");
  assert.doesNotMatch(JSON.stringify(buyer), /Merchant-only note/);
  const replacement = await client.issueCustomerLink(created.id);
  assert.equal((await buyerView(link.token)).status, 404);
  assert.equal((await client.revokeCustomerLink(created.id)).active, false);
  assert.equal((await buyerView(replacement.token)).status, 404);
});

test("an app customer opens order support with an opted-in key and receives safe progress", { timeout: 90_000 }, async (t) => {
  const { baseUrl, key, commerceKey } = await fastApi(t);
  const response = await fetch(baseUrl + "/platform/support-keys", {
    method: "POST", headers: { Authorization: "Bearer " + key, "Content-Type": "application/json" },
    body: JSON.stringify({ source: "sdk-aftercare" }),
  });
  assert.equal(response.status, 201);
  const issued = await response.json();
  const app = new ResolveClient({ baseUrl, apiKey: issued.api_key, source: "sdk-aftercare" });
  await app.syncOrder({ id: "SDK-SUPPORT-1", status: "paid", items:[{product_id:"ITEM1",quantity:1}] });
  assert.equal((await app.getOrderResolution("SDK-SUPPORT-1")).stage, "no_issue");
  const ordinary = new ResolveClient({ baseUrl, apiKey: commerceKey, source: "sdk-aftercare" });
  await assert.rejects(ordinary.getOrderResolution("SDK-SUPPORT-1"), { status: 403 });
  const input = { orderId: "SDK-SUPPORT-1", requestId: crypto.randomUUID(), reason: "damaged_item", message: "The handle arrived broken.", requestedResolution: "replacement", privateInternalNote: "do not forward" };
  const actualFetch=globalThis.fetch;let committedResponseLost=false;let issue;
  try {
    globalThis.fetch=async(url,init)=>{const response=await actualFetch(url,init);if(String(url).endsWith("/aftercare/issues")&&!committedResponseLost){committedResponseLost=true;await response.arrayBuffer();throw new TypeError("Connection lost after the backend committed");}return response;};
    issue=await app.openIssue(input);
  } finally {globalThis.fetch=actualFetch;}
  assert.equal(committedResponseLost,true);

  assert.deepEqual(await app.openIssue(input), issue);
  await assert.rejects(app.openIssue({ ...input, message: "Changed request" }), { status: 409, code: "issue_conflict" });
  const progress = await app.getOrderResolution("SDK-SUPPORT-1");
  assert.equal(progress.stage, "under_review");
  assert.equal(progress.next_action, "wait");
  assert.equal(progress.issue_count, 1);
  assert.equal(progress.authorizes_payment, false);
  assert.deepEqual(await app.lookupIssue("SDK-SUPPORT-1",input.requestId),issue);
  assert.equal((await app.getSupportContext("SDK-SUPPORT-1")).messages[0].body,input.message);
  assert.equal((await app.getRefundJourney("SDK-SUPPORT-1")).bank_receipt_verified,false);
  assert.equal((await app.getReturnEligibility("SDK-SUPPORT-1",{items:[{product_id:"ITEM1",quantity:1}]})).decision,"eligible");
  const returned=await app.requestOrderReturn("SDK-SUPPORT-1",{requestId:crypto.randomUUID(),items:[{product_id:"ITEM1",quantity:1}],reason:"Broken handle"});
  const owner=new ResolveClient({baseUrl,apiKey:key});
  const guide=await owner.saveReturnGuide(issue.case_id,returned.id,{expected_revision:0,instructions:"Use this saved label and keep the drop-off receipt.",return_address:"Synthetic warehouse",shipping_paid_by:"merchant"});
  assert.equal(guide.revision,1);
  const pdf="%PDF-1.4\nSynthetic SDK label\n%%EOF";
  const saved=await owner.uploadReturnLabel(issue.case_id,returned.id,{filename:"sdk-label.pdf",content_base64:btoa(pdf)});
  assert.equal((await app.getReturnGuide("SDK-SUPPORT-1",returned.id)).labels[0].id,saved.id);
  assert.equal(atob((await app.downloadReturnLabel("SDK-SUPPORT-1",returned.id,saved.id)).content_base64),pdf);
  const feed=await app.pullEvents();
  assert.equal(feed.items[0].type,"resolution.updated");
  assert.equal((await app.pullEvents({afterSequence:feed.next_after_sequence})).items.length,0);

  const link = await app.createSupportLink("SDK-SUPPORT-1");
  assert.equal(new URL(link.public_url).hash.slice(1), link.token);
  const portal = await fetch(baseUrl + "/customer-portal/view", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token: link.token }) });
  assert.equal(portal.status, 200);
  assert.equal((await portal.json()).messages[0].body, input.message);
  await assert.rejects(app.getCase(issue.case_id), { status: 401 });
  const wrongSource = new ResolveClient({ baseUrl, apiKey: issued.api_key, source: "other-app" });
  await assert.rejects(wrongSource.getOrderResolution("SDK-SUPPORT-1"), { status: 403 });
});

test("ORDER-1042: evidence SDK verifies a partial refund without exposing merchant data", {
  timeout: 90_000,
  skip: process.env.RESOLVE_RUN_SDK_EVIDENCE_SIMULATION !== "1",
}, async (t) => {
  const { baseUrl, key, otherKey } = await fastApi(t, true);
  const resolve = new ResolveClient({ baseUrl, apiKey: key, timeoutMs: 30_000 });
  const other = new ResolveClient({ baseUrl, apiKey: otherKey });
  const reference = "SIMHSDK1042";
  const control = async (action, data, id = reference) => {
    const response = await fetch(baseUrl + "/__fixture/paypal/" + action + "/" + id, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data),
    });
    assert.equal(response.status, 200);
    return response.json();
  };
  const input = { external_reference: "ORDER-1042", order_reference: "ORDER-1042", title: "Private support investigation" };
  const [created, reused] = await Promise.all([resolve.upsertCase(input), resolve.upsertCase(input)]);
  assert.equal(created.id, reused.id);
  await assert.rejects(resolve.upsertCase({ ...input, title: "Different title" }), { status: 409, code: "case_reference_conflict" });
  const linkInput = { kind: "paypal_capture", reference };
  const [record, duplicateRecord] = await Promise.all([resolve.linkRecord(created.id, linkInput), resolve.linkRecord(created.id, linkInput)]);
  assert.equal(record.id, duplicateRecord.id);
  assert.equal(record.verification, "association_only");
  await assert.rejects(resolve.linkRecord(created.id, { ...linkInput, source: "different-app" }), { status: 409, code: "record_conflict" });
  await resolve.linkRecord(created.id, { kind: "support_ticket", reference: "PRIVATE-TICKET-1042" });
  const approval = {
    source: "shop-helpdesk", source_event_id: "approval-1042", evidence_type: "refund_approved",
    occurred_at: "2026-11-07T11:00:00Z", summary: "Private note: manager approved the USD 25 refund.",
    amount: "25.00", currency: "USD",
  };
  const [receipt, duplicateEvent] = await Promise.all([
    resolve.addEvidence(created.id, approval),
    resolve.addEvidence(created.id, { ...approval, amount: "25", occurred_at: "2026-11-07T16:30:00+05:30" }),
  ]);
  assert.equal(receipt.id, duplicateEvent.id);
  assert.equal(receipt.verification, "merchant_reported");
  await assert.rejects(resolve.addEvidence(created.id, { ...approval, amount: "24.00" }), { status: 409, code: "evidence_event_conflict" });
  const prior = (await resolve.getCase(created.id)).evidence_summary;
  assert.equal(prior.last_merchant_approval.amount, "25.00");
  assert.equal(prior.provider_completed_amount, "0.00");
  assert.ok(prior.issues.some(item => item.kind === "refund_confirmation" && item.status === "missing"));

  const external = await control("external", { cents: 2500, status: "COMPLETED" });
  const first = await resolve.refreshEvidence(created.id);
  assert.equal(first.order_history_verified, true);
  assert.ok(first.issues.some(item => item.kind === "support_ticket" && item.status === "unsupported"));
  const refund = first.verified.find(item => item.kind === "paypal_refund");
  assert.equal(refund.reference, external.id);
  assert.equal(refund.status, "COMPLETED");
  assert.equal(refund.amount, "25.00");
  assert.equal(refund.currency, "USD");
  assert.equal(refund.checked_at, first.checked_at);

  const again = await resolve.refreshEvidence(created.id);
  assert.equal(again.verified.find(item => item.kind === "paypal_refund").reference, external.id);
  const timeline = await resolve.getTimeline(created.id);
  const recorded = timeline.items.filter(item => item.data.evidence_type === "refund_approved");
  const confirmed = timeline.items.filter(item => item.data.kind === "paypal_refund");
  assert.equal(recorded.length, 1);
  assert.equal(recorded[0].source, "merchant_recorded");
  assert.equal(confirmed.length, 1);
  assert.equal(confirmed[0].source, "provider_confirmed");
  const page = await resolve.getTimeline(created.id, { limit: 1 });
  assert.ok(page.next_before_sequence);
  await resolve.addEvidence(created.id, { source: "shop-helpdesk", source_event_id: "note-1042",
    evidence_type: "support_note", occurred_at: approval.occurred_at, summary: "Private follow-up note" });
  const next = await resolve.getTimeline(created.id, { limit: 1, before_sequence: page.next_before_sequence });
  assert.equal(next.items[0].id, timeline.items[1].id);

  const bundle = await resolve.getEvidenceBundle(created.id);
  assert.ok(bundle.linked_records.some(item => item.reference === reference));
  assert.equal(bundle.case.evidence_summary.provider_completed_amount, "25.00");
  assert.equal(bundle.case.evidence_summary.refund_status, "partially_refunded");
  assert.equal(bundle.case.evidence_summary.last_checked_at, again.checked_at);
  assert.equal(bundle.case.evidence_summary.issues.some(item => item.kind === "refund_confirmation"), false);
  assert.equal(bundle.case.refund_case_id, null);

  await assert.rejects(other.getCase(created.id), { status: 404 });
  await assert.rejects(other.getTimeline(created.id), { status: 404 });
  await assert.rejects(other.getEvidenceBundle(created.id), { status: 404 });
  await assert.rejects(other.refreshEvidence(created.id), { status: 404 });
  await assert.rejects(other.addEvidence(created.id, approval), { status: 404 });
  await assert.rejects(other.linkRecord(created.id, linkInput), { status: 404 });
  await assert.rejects(other.createBuyerLink(created.id), { status: 404 });

  await control("evidence-outage", { enabled: true });
  const failed = await resolve.refreshEvidence(created.id);
  assert.deepEqual(failed.verified, []);
  assert.ok(failed.issues.some(item => item.kind === "paypal_capture" && item.status === "unavailable"));
  assert.doesNotMatch(JSON.stringify(failed), /DO-NOT-LEAK/);
  const retained = (await resolve.getCase(created.id)).evidence_summary;
  assert.equal(retained.provider_completed_amount, "25.00");
  assert.equal(retained.last_checked_at, failed.checked_at);
  assert.equal(retained.last_verified_at, again.checked_at);
  assert.equal(retained.order_history_verified, false);

  const buyer = await resolve.createBuyerLink(created.id, { show_order_reference: true });
  const reply = await fetch(baseUrl + "/customer-portal/view", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token: buyer.token }),
  });
  assert.equal(reply.status, 200);
  const projection = await reply.json();
  assert.equal(projection.order_reference, "ORDER-1042");
  assert.ok(projection.timeline.some(item => item.label === "PayPal confirmed a partial refund"));
  assert.ok(projection.timeline.some(item => item.label === "Merchant recorded a refund approval"));
  assert.doesNotMatch(JSON.stringify(projection), /Private|PRIVATE-TICKET|SIMHSDK|SIMEXT/);
  assert.equal((await control("state", {})).refund_posts, 0);

  const noParent = await resolve.upsertCase({ external_reference: "ORDER-OTHER", title: "Capture-only check" });
  const noParentCapture = "SIMHSDKNOPARENT";
  await resolve.linkRecord(noParent.id, { kind: "paypal_capture", reference: noParentCapture });
  const pending = await control("external", { cents: 1000, status: "PENDING" }, noParentCapture);
  await resolve.linkRecord(noParent.id, { kind: "paypal_refund", reference: pending.id });
  const partial = await resolve.refreshEvidence(noParent.id);
  assert.equal(partial.order_history_verified, false);
  assert.ok(partial.issues.some(item => item.kind === "paypal_order" && item.status === "missing"));
  const pendingStatus = (await resolve.getCase(noParent.id)).evidence_summary;
  assert.equal(pendingStatus.refund_status, "pending");
  assert.equal(pendingStatus.provider_pending_amount, "10.00");
  assert.equal(pendingStatus.provider_completed_amount, "0.00");

  const exampleCapture = "SIMHSDKEXAMPLE";
  await control("external", { cents: 2500, status: "COMPLETED" }, exampleCapture);
  const example = fileURLToPath(new URL("../examples/order-1042.mjs", import.meta.url));
  const report = JSON.parse(execFileSync(process.execPath, [example], {
    encoding: "utf-8", timeout: 20_000, windowsHide: true,
    env: { ...process.env, RESOLVE_API_URL: baseUrl, RESOLVE_API_KEY: key, RESOLVE_EXTERNAL_REFERENCE: "ORDER-EXAMPLE",
      PAYPAL_CAPTURE_ID: exampleCapture, PAYPAL_ORDER_ID: "SIMORDER" + exampleCapture },
  }));
  assert.equal(report.refundStatus, "partially_refunded");
  assert.ok(report.verified.some(item => item.kind === "paypal_refund" && item.amount === "25.00"));
});

async function listen(t, handler) {
  const server = createServer(handler);
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  t.after(() => {
    server.closeAllConnections();
    return new Promise((resolve) => server.close(resolve));
  });
  return `http://127.0.0.1:${server.address().port}`;
}

test("never follows a redirect or copies error bodies that could contain secrets", async (t) => {
  let forwarded = 0;
  const sink = await listen(t, (_req, res) => { forwarded++; res.end("{}"); });
  const api = await listen(t, (req, res) => {
    assert.equal(req.headers.authorization, "Bearer " + fixtureKey);
    if (req.method === "GET") return res.writeHead(307, { Location: sink }).end();
    res.writeHead(422, { "Content-Type": "application/json" }).end(JSON.stringify({ detail: fixtureKey }));
  });
  const client = new ResolveClient({ baseUrl: api, apiKey: fixtureKey });
  await assert.rejects(client.getMerchant(), { name: "ResolveApiError", status: 307 });
  assert.equal(forwarded, 0);
  await assert.rejects(client.createCase({ title: "Fixture" }), (error) =>
    error instanceof ResolveApiError && error.status === 422 && !JSON.stringify(error).includes(fixtureKey));
  assert.throws(() => new ResolveClient({ baseUrl: "http://resolve.example.test", apiKey: fixtureKey }), TypeError);
});

test("classifies timeouts, cancellation and invalid responses", async (t) => {
  const api = await listen(t, (req, res) => {
    if (req.url === "/slow/auth/me") return;
    res.writeHead(200, { "Content-Type": "text/html" }).end("<html>Wrong service</html>");
  });
  const slow = new ResolveClient({ baseUrl: api + "/slow", apiKey: fixtureKey, timeoutMs: 75 });
  const wrong = new ResolveClient({ baseUrl: api, apiKey: fixtureKey });
  await assert.rejects(slow.getMerchant(), (error) => error instanceof ResolveTransportError && error.code === "timeout");
  await assert.rejects(wrong.getMerchant({ signal: AbortSignal.abort() }), { code: "aborted" });
  await assert.rejects(wrong.getMerchant(), { code: "invalid_response" });
});

test("commerce SDK sends only projected fields and reports invalid source queries", { timeout: 90_000 }, async (t) => {
  const { baseUrl, commerceKey, key } = await fastApi(t);
  const resolve = new ResolveClient({ baseUrl, apiKey: commerceKey });
  const merchant = new ResolveClient({ baseUrl, apiKey: key });
  const order = {
    source: "direct-api", order_reference: "ORDER-52", revision: 1, password: "dont-send",
    order_status: "delivered", payment: { status: "completed", currency: "USD", apiSecret: "dont-send" },
    items: [{ product_id: "P-52", quantity: 1, rawUser: { password_hash: "dont-send" } }],
    contact: { email: "customer@example.test", password_hash: "dont-send" },
  };
  const receipt = await resolve.syncCommerceOrder(order);
  assert.equal((await resolve.getCommerceOrder(receipt.case_id)).app.items[0].product_id, "P-52");
  assert.equal((await merchant.getCommerceContact(receipt.case_id)).email, "customer@example.test");
  await assert.rejects(resolve.getCommerceContact(receipt.case_id), { status: 401 });
  assert.throws(() => resolve.syncCommerceOrder({ ...order, order_status: { password_hash: "dont-send" } }), {
    name: "TypeError",
  });
  await assert.rejects(resolve.syncCommerceOrder({ ...order, order_status: "changed" }), {
    status: 409, code: "commerce_conflict",
  });
  const missing = resolve.connectPostgres({ async query(sql, values) {
    assert.match(sql, /o\.order_reference = \$1/);
    assert.doesNotMatch(sql, /resolve_evidence\.contacts/);
    assert.deepEqual(values, ["ORDER-52"]);
    return { rows: [] };
  } }, { source: "source" });
  await assert.rejects(missing.sync("ORDER-52"), { code: "order_not_found" });
  const broken = resolve.connectPostgres({ async query() { throw new Error("dont-send"); } }, { source: "source" });
  await assert.rejects(broken.sync("ORDER-52"), (error) => {
    assert.equal(error.code, "database_error");
    assert.doesNotMatch(String(error), /dont-send/);
    return true;
  });
});

test("commerce SDK reads a real PostgreSQL app and finds PayPal differences without moving money", {
  timeout: 90_000,
  skip: process.env.RESOLVE_RUN_SDK_EVIDENCE_SIMULATION !== "1" || !process.env.RESOLVE_COMMERCE_TEST_APP_ADMIN_URL,
}, async (t) => {
  const { baseUrl, key, commerceKey, otherKey } = await fastApi(t, true);
  const { appDatabase } = await import("./app-postgres.mjs");
  const { owner, reader, readUrl } = await appDatabase(t, process.env.RESOLVE_COMMERCE_TEST_APP_ADMIN_URL);
  const resolve = new ResolveClient({ baseUrl, apiKey: commerceKey, timeoutMs: 30_000 });
  const merchant = new ResolveClient({ baseUrl, apiKey: key });
  const other = new ResolveClient({ baseUrl, apiKey: otherKey });
  const evidence = resolve.connectPostgres(reader, { source: "merchant-store" });
  const capture = "SIMHSDKCOMMERCE";
  const control = async (operation, value) => {
    const response = await fetch(baseUrl + "/__fixture/paypal/" + operation + "/" + capture, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(value),
    });
    assert.equal(response.status, 200);
    return response.json();
  };
  await assert.rejects(reader.query("SELECT password_hash FROM public.users"), { code: "42501" });
  await assert.rejects(reader.query("UPDATE resolve_evidence.orders SET order_status='edited'"), { code: "42501" });
  const catalog = [];
  for await (const imported of evidence.registerAll({ pageSize: 1 })) catalog.push(imported);
  assert.deepEqual(catalog.map(row => [row.order_reference, row.case_id]), [["STORE-2042", null]]);
  assert.equal((await merchant.listCases()).total, 0);
  const report = await evidence.inspect("STORE-2042");
  const id = report.case_id;
  assert.equal(report.status, "match");
  assert.equal(report.app.customer_reference, "USER-42");
  assert.equal(report.app.items[0].name, "Desk lamp");
  assert.equal(report.app.items[0].unit_amount, "50.00");
  assert.equal(report.app.payment.captured_amount, "100.00");
  await assert.rejects(merchant.getCommerceContact(id), { status: 404 });
  await assert.rejects(other.getCommerceOrder(id), { status: 404 });

  await control("external", { cents: 2500, status: "COMPLETED" });
  const changed = await resolve.refreshCommerceOrder(id);
  assert.equal(changed.status, "mismatch");
  assert.deepEqual(changed.checks.filter(row => row.status === "mismatch").map(row => [
    row.field, row.app_value, row.paypal_value,
  ]), [["payment_status", "completed", "partially_refunded"], ["refunded_amount", "0.00", "25.00"]]);
  assert.equal((await merchant.getEvidenceBundle(id)).commerce.status, "mismatch");

  const { readFile } = await import("node:fs/promises");
  const optionalContact = await readFile(new URL("../examples/postgres-contact-view.sql", import.meta.url), "utf8");
  await owner.query(optionalContact.replace("(order_reference, name, email, phone)", "(order_reference, email)"));
  await assert.rejects(reader.query("SELECT phone FROM resolve_evidence.contacts"), { code: "42501" });
  await owner.query("BEGIN; UPDATE public.payments SET status='partially_refunded', refunded_amount=25.00; UPDATE public.orders SET evidence_revision=2; COMMIT");
  const contacts = resolve.connectPostgres(reader, { source: "merchant-store", contactFields: ["email"] });
  assert.equal((await contacts.sync("STORE-2042")).case_id, id);
  const stale = await resolve.getCommerceOrder(id);
  assert.equal(stale.status, "incomplete");
  assert.ok(stale.checks.every(item => item.status === "unverified"));
  assert.equal((await contacts.inspect("STORE-2042")).status, "match");
  assert.deepEqual(await merchant.getCommerceContact(id), {
    name: null, email: "buyer@example.test", phone: null,
  });
  assert.doesNotMatch(JSON.stringify(await merchant.getEvidenceBundle(id)), /buyer@example\.test|never-export-password/);

  const example = fileURLToPath(new URL("../examples/connect-postgres.mjs", import.meta.url));
  const exampleResult = JSON.parse(execFileSync(process.execPath, [example, "STORE-2042"], {
    encoding: "utf-8", timeout: 20_000, windowsHide: true,
    env: { ...process.env, RESOLVE_API_URL: baseUrl, RESOLVE_API_KEY: commerceKey, APP_EVIDENCE_DATABASE_URL: readUrl },
  }));
  assert.equal(exampleResult.status, "match");

  const different = await resolve.syncCommerceOrder({
    source: "another-store-flow", order_reference: "STORE-WRONG-ORDER", revision: 1,
    payment: { paypal_order_id: "WRONGORDER", paypal_capture_id: capture,
      status: "partially_refunded", captured_amount: "99.00", refunded_amount: "25.00" },
  });
  const wrongOrder = await resolve.refreshCommerceOrder(different.case_id);
  assert.equal(wrongOrder.status, "mismatch");
  assert.deepEqual(wrongOrder.checks.filter(row => row.status === "mismatch").map(row => row.field),
    ["paypal_order_id", "captured_amount"]);
  assert.equal(wrongOrder.checks.find(row => row.field === "refunded_amount").status, "unverified");
  assert.ok(wrongOrder.provider_issues.some(item => item.kind === "paypal_order_reference"));

  await control("evidence-outage", { enabled: true });
  const unavailable = await resolve.refreshCommerceOrder(id);
  assert.equal(unavailable.status, "incomplete");
  assert.ok(unavailable.checks.every(item => item.status === "unverified"));
  assert.equal((await merchant.getCase(id)).evidence_summary.provider_completed_amount, "25.00");
  assert.equal((await control("state", {})).refund_posts, 0);
  await owner.query("INSERT INTO public.payments SELECT * FROM public.payments LIMIT 1");
  await assert.rejects(contacts.sync("STORE-2042"), { code: "unsupported_order" });
});

test("publish app orders and resume PostgreSQL backfill without creating cases", { timeout: 90_000 }, async (t) => {
  const { baseUrl, key, commerceKey } = await fastApi(t);
  const resolve = new ResolveClient({ baseUrl, apiKey: commerceKey });
  const merchant = new ResolveClient({ baseUrl, apiKey: key });
  const refs = ["BATCH-1", "BATCH-2", "BATCH-3"];
  const pages = [];
  const source = resolve.connectPostgres({ async query(sql, values) {
    if (sql.startsWith("SELECT order_reference FROM")) {
      assert.match(sql, /LIMIT \$2::int/);
      pages.push(values[0]);
      return { rows: refs.filter(ref => ref > values[0]).slice(0, Number(values[1])).map(order_reference => ({ order_reference })) };
    }
    return { rows: [{ order_reference: values[0], revision: "1", order_status: "created", payments: [], items: [] }] };
  } }, { source: "warehouse" });
  const first = await source.register("BATCH-1");
  assert.equal(first.case_id, null);
  const imported = [];
  for await (const row of source.registerAll({ after: first.order_reference, pageSize: 1 })) imported.push(row);
  assert.deepEqual(pages, ["BATCH-1", "BATCH-2", "BATCH-3"]);
  assert.deepEqual(imported.map(row => row.order_reference), ["BATCH-2", "BATCH-3"]);
  assert.equal((await source.register("BATCH-1")).id, first.id);
  assert.equal((await merchant.listCases()).total, 0);
  const list = await fetch(baseUrl + "/commerce/orders?source=warehouse", { headers: { Authorization: "Bearer " + key } });
  assert.equal((await list.json()).total, 3);
});

test("createResolve reads the copied server environment and syncOrder sends a versioned order", { timeout: 90_000 }, async (t) => {
  const { baseUrl, key, commerceKey } = await fastApi(t);
  const values = { RESOLVE_API_URL: baseUrl, RESOLVE_API_KEY: commerceKey, RESOLVE_APP_SOURCE: "easy-store" };
  const previous = Object.fromEntries(Object.keys(values).map(name => [name, process.env[name]]));
  let resolve;
  try {
    Object.assign(process.env, values);
    resolve = createResolve();
  } finally {
    for (const [name, value] of Object.entries(previous)) {
      if (value === undefined) delete process.env[name];
      else process.env[name] = value;
    }
  }
  const first = await resolve.syncOrder({ id: "EASY-ORDER-23", status: "paid" });
  assert.equal(first.case_id, null);
  assert.equal(first.revision, 1);
  assert.equal(first.source, "easy-store");
  const next = await resolve.syncOrder({ id: "EASY-ORDER-23", version: 2, status: "shipped" });
  assert.equal(first.id, next.id);
  const catalog = await fetch(baseUrl + "/commerce/orders", { headers: { Authorization: "Bearer " + key } });
  const { items } = await catalog.json();
  assert.equal(items[0].order_status, "shipped");
  await assert.rejects(resolve.syncOrder({ id: "EASY-ORDER-23", status: "paid" }), { status: 409, code: "commerce_conflict" });
});


test("retry-safe support writes retain identity after an ambiguous network outcome", async () => {
  const original=globalThis.fetch;let calls=0;const bodies=[];
  try {
    globalThis.fetch=async(_url,init)=>{calls++;bodies.push(init.body);if(calls===1)throw new TypeError("Connection lost after commit");return new Response(JSON.stringify({issue_id:"synthetic"}),{status:201,headers:{"Content-Type":"application/json"}});};
    const app=new ResolveClient({baseUrl:"http://127.0.0.1:12345",apiKey:fixtureKey,source:"retry-test"});
    await app.openIssue({orderId:"ORDER1",requestId:crypto.randomUUID(),reason:"other",message:"Saved issue"});
    assert.equal(calls,2);assert.equal(bodies[0],bodies[1]);
    calls=0;globalThis.fetch=async()=>{calls++;throw new TypeError("Unknown link outcome");};
    await assert.rejects(app.createSupportLink("ORDER1"),{code:"network"});assert.equal(calls,1);
    calls=0;globalThis.fetch=async()=>{calls++;return new Response("private validation detail",{status:409});};
    await assert.rejects(app.openIssue({orderId:"ORDER1",requestId:crypto.randomUUID(),reason:"other",message:"Different"}),{status:409});assert.equal(calls,1);
  } finally {globalThis.fetch=original;}
});

test("PostgreSQL event consumer rolls back callbacks, deduplicates concurrency and ignores older revisions", {skip:process.env.RESOLVE_RUN_EVENT_CONSUMER_PG!=="1",timeout:90000}, async t=>{
  const {Pool}=await import("pg");
  const admin=new Pool({connectionString:"postgresql://resolve_synthetic@127.0.0.1:56440/resolve_operations"});
  const schema="sdk_consumer_"+crypto.randomUUID().replaceAll("-","");
  await admin.query('CREATE SCHEMA "'+schema+'"');
  const pool=new Pool({connectionString:"postgresql://resolve_synthetic@127.0.0.1:56440/resolve_operations",options:"-c search_path="+schema});
  t.after(async()=>{await pool.end();await admin.query('DROP SCHEMA "'+schema+'" CASCADE');await admin.end();});
  const merchant=crypto.randomUUID();
  const consumer=new PostgresResolutionConsumer(pool,{consumerId:"order-page",merchantId:merchant,source:"store"});
  await consumer.initialize();
  await pool.query("CREATE TABLE updates (version INTEGER NOT NULL)");
  const event=(sequence,revision)=>({id:crypto.randomUUID(),sequence,revision,source:"store",order_reference:"ORDER1",snapshot:{resolution:{stage:"under_review"}},created_at:new Date().toISOString(),type:"resolution.updated"});
  const page=items=>({merchant_id:merchant,source:"store",items,next_after_sequence:items.at(-1)?.sequence??0,has_more:false,reconciled_orders:1});
  const first=page([event(1,1)]);
  await assert.rejects(consumer.apply(first,async(e,db)=>{await db.query("INSERT INTO updates VALUES ($1)",[e.revision]);throw new Error("App transaction failed");}),/App transaction failed/);
  assert.equal(await consumer.cursor(),0);assert.equal((await pool.query("SELECT * FROM updates")).rows.length,0);
  const results=await Promise.all([consumer.apply(first,async(e,db)=>{await db.query("INSERT INTO updates VALUES ($1)",[e.revision]);}),consumer.apply(first,async(e,db)=>{await db.query("INSERT INTO updates VALUES ($1)",[e.revision]);})]);
  assert.equal(results.reduce((sum,x)=>sum+x.applied,0),1);assert.equal((await pool.query("SELECT * FROM updates")).rows.length,1);
  await consumer.apply(page([event(3,3)]),async(e,db)=>{await db.query("INSERT INTO updates VALUES ($1)",[e.revision]);});
  const stale=await consumer.apply(page([event(4,2)]),async()=>{throw new Error("Older revision must not apply");});
  assert.equal(stale.skipped,1);assert.equal(await consumer.cursor(),4);
  await assert.rejects(consumer.apply({...first,merchant_id:crypto.randomUUID()},async()=>{}),/another consumer scope/);
});
