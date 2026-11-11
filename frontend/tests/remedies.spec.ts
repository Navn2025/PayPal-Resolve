import { expect, test, type Page } from "@playwright/test";

const FIXTURE_TOKEN = "rslv_ui_test_fixture_key_not_a_real_secret";

async function signIn(page: Page) {
  await page.goto("/workspace");
  await page.getByLabel("Resolve access key").fill(FIXTURE_TOKEN);
  await page.getByRole("button", { name: "Sign in with access key" }).click();
  await expect(page.getByRole("button", { name: /Connected refund fixture/ }).first()).toBeVisible();
}

async function post<T>(page: Page, path: string, body: unknown): Promise<T> {
  return page.evaluate(async ({ path, body }) => {
    const response = await fetch("/api/resolve" + path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (!response.ok) throw new Error(`${path}: ${response.status} ${await response.text()}`);
    return response.json();
  }, { path, body }) as Promise<T>;
}

// Synthetic data on the isolated fixture backend. The AI ranking and the final publish response are mocked;
// the options, the balance and the promise creation come from the real backend through the proxy.
test("suggested remedies: code options, AI ranking, then separate create and publish steps", async ({ page }) => {
  await signIn(page);
  const title = "Remedy browser case " + Date.now();
  const capture = "SIMREM" + Date.now();
  const payment = await post<{ id: string }>(page, "/cases", {
    order_id: "ORDER" + capture, complaint: title, payment: { capture_id: capture, captured_amount: "100.00" } });
  const created = await post<{ id: string }>(page, "/resolution-cases", { title, order_reference: "ORD-REM", refund_case_id: payment.id });

  await page.route(`**/api/resolve/resolution-cases/${created.id}/ai/rank-remedies`, (route) => route.fulfill({ json: {
    case_id: created.id, source: "ai", label: "AI suggestion – verify before acting", fallback_reason: null,
    issue: "damaged", buyer_preference: "keep_item", tokens: 120, cache_hit: false, guard_violations: [], model: "mocked",
    ranking: [{ option_id: "partial_refund", reason: "The buyer would rather keep the item." },
              { option_id: "refund_after_return", reason: "Full refund once it comes back." }],
    buyer_message: "Sorry about this. You can keep it with $20.00 back, or return it for $100.00." } }));
  const offers: string[] = [];
  await page.route(`**/api/platform/cases/${created.id}/offers`, async (route) => {
    offers.push(route.request().postData() ?? "");
    await route.fulfill({ status: 201, json: { id: "mocked", revision: 1 } });
  });

  await page.goto("/workspace");
  await page.getByRole("button", { name: new RegExp(title) }).click();
  const area = page.getByRole("region", { name: "Promises & AI" });
  const panel = page.getByRole("region", { name: "Suggested remedies" });
  // The first card in Promises & AI.
  await expect(area.locator("section").first()).toHaveAttribute("aria-label", "Suggested remedies");
  await expect(panel.getByText("Refundable $100.00 = $100.00 captured − $0.00 refunded − $0.00 pending.")).toBeVisible();
  const choices = panel.getByRole("radio");
  await expect(choices).toHaveCount(2);
  await expect(panel.locator(".remedy-option").first()).toContainText("Refund $100.00 after the return");
  await expect(panel.locator(".remedy-option").nth(1)).toContainText("Partial refund of $20.00");
  await panel.getByText("Not offered (2)").click();
  await expect(panel.getByText(/Store credit can be promised only after/)).toBeVisible();

  await panel.getByRole("button", { name: "Rank with AI" }).click();
  await expect(panel.getByText("AI suggestion – verify before acting")).toBeVisible();
  await expect(panel.locator(".remedy-option").first()).toContainText("1. Partial refund of $20.00");
  await expect(panel.locator(".remedy-option").first()).toContainText("The buyer would rather keep the item.");
  await expect(choices.first()).toBeChecked();
  await expect(panel.getByText(/You can keep it with \$20\.00 back/)).toBeVisible();

  await panel.getByRole("button", { name: "Create promises" }).click();
  await expect(panel.getByText(/Promises created for partial refund/)).toBeVisible();
  expect(offers).toEqual([]);  // creating promises never publishes
  const promises = page.locator(".promise-section .promise-row");
  await expect(promises).toHaveCount(1);
  await expect(promises.first()).toContainText("Partial refund of $20.00; the buyer keeps the item");

  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
  await page.setViewportSize({ width: 1440, height: 900 });

  await panel.getByRole("button", { name: "Publish offer" }).click();
  await expect(panel.getByText("Offer 1 published to the buyer.")).toBeVisible();
  expect(offers).toHaveLength(1);
  const sent = JSON.parse(offers[0]);
  expect(sent.choices).toHaveLength(1);
  expect(sent.choices[0].expected_revision).toBe(1);
  expect(new Date(sent.expires_at).getTime()).toBeGreaterThan(Date.now());
});

test("the fixture case with an open refund promise gets no new refund suggestion", async ({ page }) => {
  await signIn(page);
  await page.getByRole("button", { name: /Connected refund fixture/ }).first().click();
  const panel = page.getByRole("region", { name: "Suggested remedies" });
  await expect(panel.getByText(/No remedy to suggest: A refund promise is already open/)).toBeVisible();
  await expect(panel.getByRole("button", { name: "Create promises" })).toHaveCount(0);
});
