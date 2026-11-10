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
  const step = page.getByRole("region", { name: "Next step" });
  const check = page.getByRole("region", { name: "Promise check" });
  // Fixture: accepted $30 refund promise, nothing refunded yet, gated behind a return milestone.
  // Amounts appear once, in the money summary; the promise check shows status and timing only.
  await expect(page.locator(".money-outstanding")).toContainText("$30.00");
  await expect(page.locator(".money-confirmed")).toContainText("$0.00");
  await expect(check.getByLabel("Promise At risk")).toContainText(/Due [A-Z][a-z]{2} \d{1,2}/);
  await expect(check.getByLabel("Promise At risk")).toContainText("0 days since promise");
  await expect(check.locator(".money-rows")).toHaveCount(0);
  // One next step: the refund review is not offered while the return is unconfirmed.
  await expect(step.getByRole("heading", { name: "Check before approving" })).toBeVisible();
  await expect(step.getByRole("button", { name: "Review refund" })).toHaveCount(0);
  await expect(step.getByRole("button", { name: "Refresh evidence" })).toBeVisible();

  // Missing information is the next step's checklist, written by code from the same case.
  const missing = step.locator(".checklist li");
  // Ordered steps: the unconfirmed return comes before the missing due date.
  await expect(missing).toHaveText(["The return is not confirmed yet.", "Add a due date to the refund promise."]);
  await expect(step.getByRole("button", { name: "Explain with AI" })).toHaveClass(/button-secondary/);
  await expect(step.getByText("Advisory only. It never approves or sends a refund.")).toBeVisible();
  const summary = "Promised $30.00 after return; $0.00 refunded; $30.00 remaining; return not confirmed → confirm the return before any refund.";
  await expect(step.getByText(summary)).toBeVisible();
  // The fixture backend has AI extraction off, so the explanation falls back to the same template.
  const reloaded = page.waitForResponse((response) => /\/promise-health$/.test(new URL(response.url()).pathname));
  await step.getByRole("button", { name: "Explain with AI" }).click();
  await expect(step.getByText(/AI explanation not used: AI is turned off on this server/)).toBeVisible();
  release();
  await reloaded;
  await page.waitForTimeout(300);
  await expect(step.getByText(/AI explanation not used: AI is turned off on this server/)).toBeVisible();
  await expect(step.getByText(summary)).toBeVisible();
  await expect(step.getByText("AI explanation – verify before acting")).toHaveCount(0);

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

test("the next-step refund button pre-fills the review but never above the backend cap, and sends nothing", async ({ page }) => {
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
  const step = page.getByRole("region", { name: "Next step" });
  await expect(page.locator(".money-status")).toContainText("4 days since promise");
  await expect(page.locator(".money-status")).toContainText("At risk");
  // The single primary action opens the existing review, pre-filled with the suggested amount.
  await step.getByRole("button", { name: "Review refund" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByLabel("Refund amount (USD)")).toHaveValue("12.50");
  await expect(dialog.getByRole("button", { name: "Approve $12.50" })).toBeVisible();
  await dialog.getByRole("button", { name: "Close dialog" }).click();

  // A suggestion above the backend's recommended amount ($30.00 here) is not used.
  suggested = "45.00";
  await page.reload();
  await page.getByRole("button", { name: /Promise check browser test/ }).click();
  await step.getByRole("button", { name: "Review refund" }).click();
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
  const step = page.getByRole("region", { name: "Next step" });
  await step.getByRole("button", { name: "Explain with AI" }).click();
  await expect(step.getByText("AI explanation – verify before acting")).toBeVisible();
  await expect(step.getByText(text)).toBeVisible();
  expect(posts.filter((path) => /refund-approvals|refund-executions|promises/.test(path))).toEqual([]);
});

test("a linked payment with nothing promised shows the action as the title and ordered steps only", async ({ page }) => {
  await signIn(page);
  const make = async (title: string, agreed: boolean) => {
    const capture = "SIMSTEPS" + Date.now();
    const payment = await api<{ id: string }>(page, "/cases", {
      order_id: "ORDER" + capture, complaint: title, payment: { capture_id: capture, captured_amount: "100.00" },
      ...(agreed ? { commitment: { amount: "40.00", status: "accepted", source_message: "Agreed in chat" } } : {}),
    });
    await api(page, "/resolution-cases", { title, order_reference: "ORD-" + capture, refund_case_id: payment.id });
  };
  await make("Steps with agreed amount", true);
  await make("Steps without agreed amount", false);
  await page.reload();

  await page.getByRole("button", { name: /Steps with agreed amount/ }).click();
  const step = page.getByRole("region", { name: "Next step" });
  await expect(step.getByRole("heading", { name: "Record the refund promise" })).toBeVisible();
  await expect(step.getByText("The payment is linked, but no refund is promised yet.")).toBeVisible();
  await expect(step.getByRole("button", { name: "Record promise" })).toHaveClass(/button-primary/);
  await expect(step.locator(".checklist li")).toHaveText(["Record the refund promise."]);
  // Nothing is recorded yet, so no summary sentence or AI rewording repeats the checklist.
  await expect(step.locator(".explain")).toHaveCount(0);
  await expect(step.getByRole("button", { name: "Explain with AI" })).toHaveCount(0);
  await expect(step).not.toContainText("{recommended}");

  await page.getByRole("button", { name: /Steps without agreed amount/ }).click();
  await expect(step.getByRole("heading", { name: "Add the agreed refund amount" })).toBeVisible();
  await expect(step.locator(".checklist li")).toHaveText([
    "Add the agreed refund amount to the linked payment case.", "Record the refund promise."]);
  await expect(step.locator(".button-primary")).toHaveCount(0);
  await expect(step.locator(".explain")).toHaveCount(0);
});
