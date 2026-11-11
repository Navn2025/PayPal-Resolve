import { expect, type APIRequestContext, type Page } from "@playwright/test";

export const fixtureKey = "rslv_ui_test_fixture_key_not_a_real_secret";
export async function signInFixture(page: Page) {
  await page.goto("/login");
  await page.getByLabel("Resolve access key").fill(fixtureKey);
  await page.getByRole("button", { name: "Sign in with access key" }).click();
  await expect(page.getByRole("heading", { name: "Resolution workspace", exact: true })).toBeVisible();
}
export async function privateFixture(request: APIRequestContext) {
  const headers = { Authorization: "Bearer " + fixtureKey };
  const cases = await request.get("http://127.0.0.1:8011/resolution-cases?limit=100", { headers });
  expect(cases.ok()).toBeTruthy();
  const item = (await cases.json()).items.find((item: { title: string }) => item.title === "Connected refund fixture");
  const response = await request.post(`http://127.0.0.1:8011/resolution-cases/${item.id}/customer-link`, { headers, data: { title: "Your order support", show_order_reference: true } });
  expect(response.status()).toBe(201);
  return { caseId: item.id as string, token: (await response.json()).token as string, headers };
}
