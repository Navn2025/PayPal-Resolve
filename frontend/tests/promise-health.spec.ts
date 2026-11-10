import { expect, test, type Page } from "@playwright/test";

const FIXTURE_TOKEN = "rslv_ui_test_fixture_key_not_a_real_secret";

async function signIn(page: Page) {
  await page.goto("/workspace");
  await page.getByLabel("Resolve access key").fill(FIXTURE_TOKEN);
  await page.getByRole("button", { name: "Sign in with access key" }).click();
  await expect(page.getByRole("button", { name: /Connected refund fixture/ })).toBeVisible();
}

async function api<T>(page: Page, path: string, body?: unknown): Promise<T> {
  // Same-origin browser fetch, so the request passes the proxy's origin and session checks.
  return page.evaluate(async ({ path, body }) => {
    const response = await fetch("/api/resolve" + path, body === undefined ? {} : {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (!response.ok) throw new Error(`${path}: ${response.status} ${await response.text()}`);
    return response.json();
  }, { path, body }) as Promise<T>;
}

test("promise check reads the real backend through the proxy", async ({ page }) => {
  await signIn(page);
  // Hold reconciliation until after "Explain with AI" is clicked, so the panel's reload lands after the
  // explanation (a race first seen in the full suite). The explanation must survive unchanged facts.
  let release = () => {};
  const gate = new Promise<void>((resolve) => { release = resolve; });
  await page.route("**/api/resolve/cases/*/reconciliation", async (route) => { await gate; await route.continue(); });
  await page.getByRole("button", { name: /Connected refund fixture/ }).click();
  const panel = page.getByRole("region", { name: "Promise check" });
  // Fixture: accepted $30 refund promise, nothing refunded yet, gated behind a return milestone.
  await expect(panel.getByText(/Promised \$30\.00 · Refunded \$0\.00 · \$30\.00 at risk · 0 days/)).toBeVisible();
  await expect(panel.getByRole("button", { name: "Refund remaining $30.00" })).toBeDisabled();
  await expect(panel.getByText(/Refund review is not available yet/)).toBeVisible();

  // Missing information and the next step are written by code from the same case.
  const missing = panel.locator(".missing-list li");
  await expect(missing.filter({ hasText: "The refund promise has no due date." })).toHaveCount(1);
  await expect(missing.filter({ hasText: "The return is not confirmed yet." })).toHaveCount(1);
  const summary = "Promised $30.00 after return; $0.00 refunded; $30.00 remaining; return not confirmed → confirm the return before any refund.";
  await expect(panel.getByText(summary)).toBeVisible();
  // The fixture backend has AI extraction off, so the explanation falls back to the same template.
  const reloaded = page.waitForResponse((response) => /\/promise-health$/.test(new URL(response.url()).pathname));
  await panel.getByRole("button", { name: "Explain with AI" }).click();
  await expect(panel.getByText(/AI explanation not used: AI is turned off on this server/)).toBeVisible();
  release();
  await reloaded;
  await page.waitForTimeout(300);
  await expect(panel.getByText(/AI explanation not used: AI is turned off on this server/)).toBeVisible();
  await expect(panel.getByText(summary)).toBeVisible();
  await expect(panel.getByText("AI explanation – verify before acting")).toHaveCount(0);

  const list = await page.request.get("/api/resolve/resolution-cases/promise-health");
  expect(list.status()).toBe(200);
  const body = await list.json();
  expect(body.overdue_after_days).toBe(3);
  expect(body.items.every((item: { status: string }) => ["at_risk", "broken"].includes(item.status))).toBe(true);
  // Read-only: the proxy does not forward other methods on these paths.
  expect(await page.evaluate(async () => (await fetch("/api/resolve/resolution-cases/promise-health", { method: "POST" })).status)).toBe(404);
  const caseId = (await (await page.request.get("/api/resolve/resolution-cases")).json()).items
    .find((item: { title: string }) => item.title === "Connected refund fixture").id;
  expect(await page.evaluate(async (id) => (await fetch(`/api/resolve/resolution-cases/${id}/next-action`, { method: "POST" })).status, caseId)).toBe(404);
});

test("refund button pre-fills the review but never above the backend cap, and sends nothing", async ({ page }) => {
  await signIn(page);
  const capture = "SIMHEALTH" + Date.now();
  const payment = await api<{ id: string }>(page, "/cases", {
    order_id: "ORDER" + capture, complaint: "Promise check browser test",
    payment: { capture_id: capture, captured_amount: "100.00" },
    commitment: { amount: "30.00", status: "accepted", source_message: "Agreed refund" },
  });
  const created = await api<{ id: string }>(page, "/resolution-cases", { title: "Promise check browser test", refund_case_id: payment.id });
  await api(page, `/resolution-cases/${created.id}/promises`, {
    promise: "Refund $30", source_note: "Support chat", target: { kind: "refund", amount: "30.00" } });

  // The isolated fixture has no PayPal history, so mark the real reconciliation as current to enable review.
  await page.route(`**/api/resolve/cases/${payment.id}/reconciliation`, async (route) => {
    const response = await route.fetch();
    route.fulfill({ response, json: { ...(await response.json()), paypal_history_current: true } });
  });
  let suggested = "12.50";
  await page.route(`**/api/resolve/resolution-cases/${created.id}/promise-health`, async (route) => {
    const response = await route.fetch();
    const real = await response.json();
    route.fulfill({ response, json: { ...real, items: real.items.map((item: Record<string, unknown>) => ({
      ...item, status: "at_risk", refunded_amount: "17.50", remaining_amount: "12.50", suggested_refund_amount: suggested,
      days_since_promise: 4, overdue: true })) } });
  });
  const posts: string[] = [];
  page.on("request", (request) => { if (request.method() === "POST") posts.push(new URL(request.url()).pathname); });

  await page.reload();
  await page.getByRole("button", { name: /Promise check browser test/ }).click();
  const panel = page.getByRole("region", { name: "Promise check" });
  await expect(panel.getByText("Promised $30.00 · Refunded $17.50 · $12.50 at risk · 4 days")).toBeVisible();
  await panel.getByRole("button", { name: "Refund remaining $12.50" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByLabel("Refund amount (USD)")).toHaveValue("12.50");
  await expect(dialog.getByRole("button", { name: "Approve $12.50" })).toBeVisible();
  await dialog.getByRole("button", { name: "Close dialog" }).click();

  // A suggestion above the backend's recommended amount ($30.00 here) is not used.
  suggested = "45.00";
  await page.reload();
  await page.getByRole("button", { name: /Promise check browser test/ }).click();
  await panel.getByRole("button", { name: "Refund remaining $45.00" }).click();
  await expect(dialog.getByLabel("Refund amount (USD)")).toHaveValue("30.00");
  await dialog.getByRole("button", { name: "Close dialog" }).click();
  expect(posts.filter((path) => /refund-approvals|refund-executions/.test(path))).toEqual([]);
});

test("an AI explanation is labelled and changes nothing", async ({ page }) => {
  await signIn(page);
  const text = "Promised $30.00 after the return; nothing refunded yet, so confirm the return first.";
  await page.route("**/api/resolve/resolution-cases/*/ai/explain-next-action", (route) => route.fulfill({ json: {
    text, source: "ai", label: "AI explanation – verify before acting", fallback_reason: null, cache_hit: false } }));
  const posts: string[] = [];
  page.on("request", (request) => { if (request.method() === "POST") posts.push(new URL(request.url()).pathname); });
  await page.getByRole("button", { name: /Connected refund fixture/ }).click();
  const panel = page.getByRole("region", { name: "Promise check" });
  await panel.getByRole("button", { name: "Explain with AI" }).click();
  await expect(panel.getByText("AI explanation – verify before acting")).toBeVisible();
  await expect(panel.getByText(text)).toBeVisible();
  expect(posts.filter((path) => /refund-approvals|refund-executions|promises/.test(path))).toEqual([]);
});
