import { expect, test } from "@playwright/test";

test("merchant reviews an automatic blocked investigation without approving a refund", async ({ page, request }) => {
  await page.goto("/workspace");
  await page.getByLabel("Resolve access key").fill("rslv_ui_test_fixture_key_not_a_real_secret");
  await page.getByRole("button", { name: "Sign in with access key" }).click();
  await page.getByRole("button", { name: /Connected refund fixture/ }).click();
  await page.locator("summary").filter({hasText:"Automatic investigation"}).click();
  const panel = page.getByRole("region", { name: "Automatic investigation" });
  await expect(panel.getByRole("heading", { name: "Automatic investigation", exact: true })).toBeVisible();
  await expect(panel.getByText(/inference disabled/).first()).toBeVisible();
  await expect(panel.getByText(/Payment requires the separate refund approval/)).toBeVisible();
  await panel.getByRole("button", { name: "Approve investigation", exact: true }).click();
  await expect(panel.getByRole("status").filter({ hasText: /Review: approve/ })).toBeVisible();
  await expect(panel.getByText(/No payment authorized/)).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(panel.getByRole("heading", { name: "Automatic investigation", exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
  const cases = await request.get("http://127.0.0.1:8011/cases", { headers: { Authorization: "Bearer rslv_ui_test_fixture_key_not_a_real_secret" } });
  for (const item of (await cases.json()).items) {
    const approvals = await request.get(`http://127.0.0.1:8011/cases/${item.id}/refund-approvals`, { headers: { Authorization: "Bearer rslv_ui_test_fixture_key_not_a_real_secret" } });
    expect(await approvals.json()).toEqual([]);
    const executions = await request.get(`http://127.0.0.1:8011/cases/${item.id}/refund-executions`, { headers: { Authorization: "Bearer rslv_ui_test_fixture_key_not_a_real_secret" } });
    expect(await executions.json()).toEqual([]);
  }
});
