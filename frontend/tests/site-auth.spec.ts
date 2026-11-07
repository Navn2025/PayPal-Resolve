import { expect, test, type Page } from "@playwright/test";

const FIXTURE_TOKEN = "rslv_ui_test_fixture_key_not_a_real_secret";

async function signInWithKey(page: Page) {
  await page.getByLabel("Resolve access key").fill(FIXTURE_TOKEN);
  await page.getByRole("button", { name: "Sign in with access key" }).click();
  await expect(page).toHaveURL(/\/workspace$/);
  await expect(page.getByRole("heading", { name: "Resolution workspace" })).toBeVisible();
}

test("landing has working merchant, buyer and demo entry points on mobile", async ({ page }, info) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "From payment issue to verified resolution." })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.screenshot({ path: info.outputPath("landing-mobile.png"), fullPage: true });
  await page.getByRole("link", { name: "Track my case" }).click();
  await expect(page.getByRole("heading", { name: "Track your resolution" })).toBeVisible();
  await page.getByRole("link", { name: "Resolve home" }).click();
  await page.getByRole("link", { name: "Explore the demo" }).click();
  await expect(page.getByText("Demo mode", { exact: true })).toBeVisible();
  expect((await page.request.get("/api/resolve/resolution-cases")).status()).toBe(401);
});

test("standalone sign-in protects the workspace and keeps keys out of the browser response", async ({ page, browser }, info) => {
  await page.goto("/workspace");
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("heading", { name: "Merchant sign in" })).toBeVisible();
  const withoutScripts = await browser.newContext({ javaScriptEnabled: false });
  try {
    const initial = await withoutScripts.newPage();
    await initial.goto(page.url());
    await expect(initial.getByRole("button", { name: "Sign in with access key" })).toBeDisabled();
    await expect(initial.locator("form")).toHaveAttribute("method", "post");
  } finally { await withoutScripts.close(); }
  await expect(page.getByRole("button", { name: "Sign in with access key" })).toBeEnabled();
  await page.screenshot({ path: info.outputPath("merchant-login.png"), fullPage: true });
  await page.getByLabel("Resolve access key").fill("rslv_invalid_test_key_11111111");
  await page.getByRole("button", { name: "Sign in with access key" }).click();
  await expect(page.getByRole("region", { name: "Merchant sign in" }).getByRole("alert")).toContainText("Invalid or revoked Resolve access key");
  await signInWithKey(page);
  const cookies = await page.context().cookies();
  const cookie = cookies.find((entry) => entry.name === "resolve_merchant_session");
  expect(cookie?.httpOnly).toBe(true);
  expect(cookie?.value).toMatch(/^rweb_/);
  expect(JSON.stringify(cookies)).not.toContain(FIXTURE_TOKEN);
  const session = await (await page.request.get("/api/session")).json();
  expect(session.method).toBe("key");
  expect(session).not.toHaveProperty("token");
  await page.getByRole("link", { name: "Account settings" }).click();
  await expect(page.getByRole("heading", { name: "Account settings" })).toBeVisible();
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login$/);
  expect((await page.request.get("/api/resolve/resolution-cases")).status()).toBe(401);
});

test("PayPal sign-in links an existing merchant and uses a one-time browser callback", async ({ page }) => {
  test.skip(process.env.RESOLVE_UI_PAYPAL_LOGIN !== "1", "Requires the isolated PayPal identity simulation");
  await page.route("https://www.sandbox.paypal.com/connect?*", async (route) => {
    const authorization = new URL(route.request().url());
    const callback = new URL(authorization.searchParams.get("redirect_uri")!);
    expect(authorization.searchParams.get("scope")).toBe("openid");
    callback.searchParams.set("state", authorization.searchParams.get("state")!);
    callback.searchParams.set("code", "resolve-code-merchant");
    await route.fulfill({ status: 302, headers: { Location: callback.href } });
  });
  await page.goto("/login");
  await page.getByRole("button", { name: /Log in with PayPal/ }).click();
  await expect(page.getByRole("region", { name: "Merchant sign in" }).getByRole("alert")).toContainText("isn’t linked");
  await signInWithKey(page);
  await page.getByRole("link", { name: "Account settings" }).click();
  await page.getByRole("button", { name: "Link PayPal" }).click();
  await expect(page.getByRole("status")).toContainText("PayPal sign-in is linked");
  await page.getByRole("button", { name: "Sign out" }).click();
  await page.getByRole("button", { name: /Log in with PayPal/ }).click();
  await expect(page).toHaveURL(/\/workspace$/);
  await expect(page.getByRole("heading", { name: "Resolution workspace" })).toBeVisible();
  const state = await (await page.request.get("/api/session")).json();
  expect(state.method).toBe("paypal");
  expect(state.paypal_linked).toBe(true);
  expect(state).not.toHaveProperty("token");
  expect((await page.context().cookies()).some((cookie) => cookie.name === "resolve_paypal_flow")).toBe(false);
});
