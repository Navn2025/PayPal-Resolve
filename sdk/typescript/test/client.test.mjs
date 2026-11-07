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
import { ResolveApiError, ResolveClient, ResolveTransportError } from "@resolve-paypal/sdk";

const fixtureKey = "rslv_" + "x".repeat(43);

async function fastApi(t, paypalSimulation = false) {
  const backend = fileURLToPath(new URL("../../../backend/", import.meta.url));
  const fixture = fileURLToPath(new URL("./fixture.py", import.meta.url));
  const cleanEnv = Object.fromEntries(Object.entries(process.env).filter(([key]) => !/^RESOLVE_/i.test(key)));
  const runtime = spawnSync("uv", ["run", "--no-sync", "python", "-c", "import sys; print(sys.executable)"], {
    cwd: backend, encoding: "utf-8", env: cleanEnv, timeout: 15_000, windowsHide: true,
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
    once(lines, "line", { signal: AbortSignal.timeout(15_000) }).then(([line]) => line),
    stopped.then(() => { throw new Error("The isolated Resolve test server exited."); }),
  ]);
  const { port, key, otherKey } = JSON.parse(firstLine);
  const baseUrl = `http://127.0.0.1:${port}`;
  for (let attempts = 0; attempts < 30; attempts++) {
    const ok = await fetch(baseUrl + "/health", { signal: AbortSignal.timeout(500) })
      .then((response) => response.ok).catch(() => false);
    if (ok) return { baseUrl, key, otherKey };
    await delay(150);
  }
  throw new Error("The isolated Resolve test server did not become healthy.");
}

test("packaged client runs a case and private buyer link lifecycle against FastAPI", { timeout: 45_000 }, async (t) => {
  const { baseUrl, key, otherKey } = await fastApi(t);
  const client = new ResolveClient({ baseUrl, apiKey: key });
  const other = new ResolveClient({ baseUrl, apiKey: otherKey });
  assert.equal((await client.getMerchant()).name, "SDK test workspace");
  const created = await client.createCase({ title: "Merchant-only note", order_reference: "ORDER-421" });
  assert.equal((await client.getCase(created.id)).outcome, created.outcome);
  assert.equal((await client.listCases({ limit: 1, offset: 0 })).items[0].id, created.id);
  assert.equal((await client.listCases({ limit: 1, offset: 1 })).items.length, 0);
  assert.equal((await other.listCases()).total, 0);
  await assert.rejects(other.getCase(created.id), (error) => error instanceof ResolveApiError && error.status === 404);
  assert.ok(Array.isArray((await client.getCaseTimeline(created.id)).items));

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

test("ORDER-1042: evidence SDK verifies a partial refund without exposing merchant data", {
  timeout: 60_000,
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
