// Native HTTP test of the real Next merchant gateway and disposable FastAPI fixture.
// No browser, dotenv loading, or subprocess spawning in this test.
import assert from "node:assert/strict";
import { test } from "node:test";

test("merchant session gateway exposes private advisory review with CSRF and stale-state protection", { timeout: 90000 }, async () => {
  const origin = process.env.RESOLVE_AI_UI_TEST_ORIGIN ?? "http://127.0.0.1:3107";
  assert.equal(new URL(origin).hostname, "127.0.0.1");
  const login = await fetch(origin + "/api/session", { method: "POST", headers: { Origin: origin, "Content-Type": "application/json" }, body: JSON.stringify({ token: "rslv_ui_test_fixture_key_not_a_real_secret" }), signal: AbortSignal.timeout(30000) });
  assert.equal(login.status, 200);
  const cookie = login.headers.getSetCookie().map((value) => value.split(";")[0]).join("; ");
  assert.ok(cookie.includes("resolve_merchant_session="));
  const headers = { Cookie: cookie, Origin: origin, "Content-Type": "application/json" };
  const cases = await fetch(origin + "/api/resolve/resolution-cases", { headers });
  assert.equal(cases.status, 200);
  const item = (await cases.json()).items.find((entry) => entry.title === "Connected refund fixture");
  assert.ok(item);
  const path = origin + `/api/resolve/resolution-cases/${item.id}/investigations`;
  const response = await fetch(path, { headers });
  assert.equal(response.status, 200);
  assert.match(response.headers.get("cache-control"), /private.*no-store/);
  const investigation = (await response.json()).items.find((entry) => entry.result);
  assert.ok(investigation);
  const reviewPath = path + `/${investigation.id}/review`;
  const body = JSON.stringify({ expected_revision: investigation.case_revision, evidence_snapshot: investigation.result.evidence_snapshot, decision: "approve" });
  const wrongOrigin = await fetch(reviewPath, { method: "POST", headers: { ...headers, Origin: "https://untrusted.example.test" }, body });
  assert.equal(wrongOrigin.status, 403);
  const review = await fetch(reviewPath, { method: "POST", headers, body });
  if (investigation.review) {
    // Re-running against a fixture already reviewed in another browser session
    // must preserve that immutable decision instead of claiming a second review.
    assert.equal(review.status, 409);
    assert.equal(investigation.review.authorizes_payment, false);
  } else {
    assert.equal(review.status, 200);
    assert.equal((await review.json()).authorizes_payment, false);
  }
  const stale = await fetch(reviewPath, { method: "POST", headers, body: JSON.stringify({ expected_revision: investigation.case_revision + 1, evidence_snapshot: investigation.result.evidence_snapshot, decision: "approve" }) });
  assert.equal(stale.status, 409);
  const anonymous = await fetch(path);
  assert.equal(anonymous.status, 401);
  for (const endpoint of ["refund-approvals", "refund-executions"]) {
    const result = await fetch(origin + `/api/resolve/cases/${item.refund_case_id}/${endpoint}`, { headers });
    assert.equal(result.status, 200);
    assert.deepEqual(await result.json(), []);
  }
});
