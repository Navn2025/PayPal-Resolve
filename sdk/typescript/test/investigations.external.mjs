// Run against the disposable frontend/tests/fixture_backend.py service only.
// node --test --experimental-test-isolation=none test/investigations.external.mjs
import assert from "node:assert/strict";
import { test } from "node:test";
import { readFile } from "node:fs/promises";
import { ResolveClient } from "@resolve-paypal/sdk";

const descriptor = JSON.parse(await readFile(new URL("../../../.local/sdk-ai-fixture.json", import.meta.url), "utf8"));
const baseUrl = `http://127.0.0.1:${descriptor.port}`;
const apiKey = descriptor.key;
const resolve = new ResolveClient({ baseUrl, apiKey });

test("SDK reads and reviews a synthetic automatic investigation without payment authorization", async () => {
  const cases = await resolve.listCases();
  const item = cases.items.find((entry) => entry.title === "Automatic synthetic investigation");
  assert.ok(item, "Start the disposable UI fixture, never a regular backend.");
  const investigation = (await resolve.getInvestigations(item.id)).items.find((entry) => entry.result);
  assert.equal(investigation.state, "blocked");
  const payload = { expected_revision: investigation.case_revision, evidence_snapshot: investigation.result.evidence_snapshot, decision: "approve" };
  const review = await resolve.reviewInvestigation(item.id, investigation.id, payload);
  assert.equal(review.authorizes_payment, false);
  assert.deepEqual(await resolve.reviewInvestigation(item.id, investigation.id, payload), review);
  await resolve.addEvidence(item.id, { source: "synthetic-node-test", source_event_id: crypto.randomUUID(), evidence_type: "support_note", occurred_at: new Date().toISOString(), summary: "Synthetic new evidence invalidates this advisory review" });
  await assert.rejects(resolve.reviewInvestigation(item.id, investigation.id, payload), { status: 409 });
  assert.equal((await resolve.getInvestigations(item.id)).items[0].state, "queued");
  for (const endpoint of item.refund_case_id ? ["refund-approvals", "refund-executions"] : []) {
    const response = await fetch(baseUrl + `/cases/${item.refund_case_id}/${endpoint}`, { headers: { Authorization: "Bearer " + apiKey } });
    assert.deepEqual(await response.json(), []);
  }
});

test("SDK rejects an invalid investigation identifier before transport", async () => {
  assert.throws(() => resolve.reviewInvestigation("invalid", "../refund-executions", { expected_revision: 1, evidence_snapshot: "0".repeat(64), decision: "approve" }));
});
