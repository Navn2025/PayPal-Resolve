import { expect, test } from "@playwright/test";

const fixtureKey = "rslv_ui_test_fixture_key_not_a_real_secret";

test("merchant generates a one-time SDK setup, syncs an order and revokes the key", async ({ page, request }) => {
  await page.goto("/login?next=settings");
  await page.getByLabel("Resolve access key").fill(fixtureKey);
  await page.getByRole("button", { name: "Sign in with access key" }).click();
  await expect(page.getByRole("heading", { name: "SDK keys" })).toBeVisible();
  await page.getByRole("button", { name: "Generate SDK key" }).click();

  const field = page.getByRole("textbox", { name: "SDK server environment" });
  await expect(field).toBeVisible();
  const setup = await field.inputValue();
  const [url, secret, source] = setup.split("\n").map(line => line.slice(line.indexOf("=") + 1));
  expect(url).toBe(new URL(page.url()).origin + "/api/sdk");
  expect(source).toBe("my-app");

  const register = url + "/commerce/orders/register";
  const headers = { Authorization: "Bearer " + secret };
  const data = { source, order_reference: "SETTINGS-SDK-ORDER", revision: 1, order_status: "paid" };
  expect((await page.request.post(register, { data })).status()).toBe(401); // Browser cookie alone is not accepted.
  expect((await request.get(url + "/commerce/orders", { headers })).status()).toBe(404);
  expect((await request.post(url + "/merchant-auth/commerce-keys", { headers })).status()).toBe(404);
  const synced = await request.post(register, { headers, data });
  expect(synced.status()).toBe(200);
  expect((await synced.json()).case_id).toBeNull();

  await page.getByRole("button", { name: "Hide key" }).click();
  await expect(field).toHaveCount(0);
  await page.reload();
  await expect(field).toHaveCount(0);
  await page.getByRole("button", { name: /Revoke SDK key/ }).click();
  await page.getByRole("button", { name: "Confirm revoke" }).click();
  await expect(page.getByText("SDK key revoked.")).toBeVisible();
  expect((await request.post(register, { headers, data })).status()).toBe(401);
});
