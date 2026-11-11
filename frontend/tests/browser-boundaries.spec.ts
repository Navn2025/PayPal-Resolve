import { expect, test } from "@playwright/test";
import { signInFixture } from "./helpers";

test("stored hostile text stays text and foreign-origin writes are rejected", async ({ page }) => {
  await signInFixture(page);
  const title = '<img src=x onerror="window.__resolveXss=true">';
  await page.getByRole("button", { name: "New case", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Case title").fill(title);
  await dialog.getByRole("button", { name: "Create case", exact: true }).click();
  await expect(page.getByRole("heading", { name: title, exact: true })).toBeVisible();
  await page.reload();
  await page.getByRole("button", { name: title, exact: false }).click();
  await expect(page.getByRole("heading", { name: title, exact: true })).toBeVisible();
  expect(await page.evaluate(() => (window as Window & { __resolveXss?: boolean }).__resolveXss)).toBeUndefined();
  expect(await page.locator('img[src="x"]').count()).toBe(0);
  const denied = await page.request.post("/api/resolve/resolution-cases", {
    headers: { Origin: "https://untrusted.example" }, data: { title: "Must not be written" },
  });
  expect(denied.status()).toBe(403);
  const list = await page.request.get("/api/resolve/resolution-cases?limit=100");
  expect((await list.json()).items.some((item: { title: string }) => item.title === "Must not be written")).toBe(false);
});

test("mobile authenticated navigation survives refresh and logout removes access", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await signInFixture(page);
  for (const [path, heading] of [["/workspace/orders", "Orders"], ["/workspace/settings", "Account settings"]]) {
    await page.goto(path);
    await expect(page.getByRole("heading", { name: heading, exact: true }).first()).toBeVisible();
    await page.reload();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  }
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page).toHaveURL(/\/login$/);
  expect((await page.request.get("/api/resolve/resolution-cases")).status()).toBe(401);
  await page.goto("/workspace");
  await expect(page).toHaveURL(/\/login/);
});
