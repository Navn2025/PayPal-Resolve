import { expect, test } from "@playwright/test";

const fixtureKey = "rslv_ui_test_fixture_key_not_a_real_secret";

test("a synced app order is visible in Orders and can open a case on demand", async ({ page, request }) => {
  const response = await request.post("http://127.0.0.1:8011/commerce/orders/register", {
    headers: { Authorization: "Bearer " + fixtureKey },
    data: {
      source: "browser-catalog", order_reference: "WEB-ORDERS-4201", revision: 1,
      order_status: "paid", payment: { status: "completed", captured_amount: "28.00",
        refunded_amount: "0.00", paypal_order_id: "ORDERSUI4201", paypal_capture_id: "CAPTUREUI4201" },
      items: [{ product_id: "trail-kettle", name: "Trail Kettle", quantity: 1, unit_amount: "28.00" }],
    },
  });
  expect(response.status()).toBe(200);
  expect((await response.json()).case_id).toBeNull();

  await page.goto("/workspace/orders");
  await expect(page).toHaveURL(/\/login/);
  await page.getByLabel("Resolve access key").fill(fixtureKey);
  await page.getByRole("button", { name: "Sign in with access key" }).click();
  await expect(page.getByRole("heading", { name: "Resolution workspace" })).toBeVisible();
  await expect(page.getByRole("button", { name: /WEB-ORDERS-4201/ })).toHaveCount(0);

  await page.getByRole("link", { name: "Orders", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Orders", exact: true })).toBeVisible();
  await page.getByLabel("Search orders").fill("CAPTUREUI4201");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await expect(page.getByText("1–1 of 1 orders")).toBeVisible();
  await page.getByRole("button", { name: /WEB-ORDERS-4201/ }).click();
  const details = page.getByRole("region", { name: "Order details" });
  await expect(details.getByText("Trail Kettle")).toBeVisible();
  await expect(details.getByText("CAPTUREUI4201")).toBeVisible();
  await details.getByRole("button", { name: "Create resolution case" }).click();
  const link = details.getByRole("link", { name: "Open case" });
  await expect(link).toBeVisible();
  await link.click();
  await expect(page).toHaveURL(/\/workspace\?case=[0-9a-f-]{36}/);
  await expect(page.getByRole("heading", { name: "Connected order", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: /WEB-ORDERS-4201/ })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("link", { name: "Orders", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Orders", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: /WEB-ORDERS-4201/ })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
});
