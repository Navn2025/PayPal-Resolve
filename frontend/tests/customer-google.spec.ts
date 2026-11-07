import { expect, test } from "@playwright/test";

const fixture = "http://127.0.0.1:8011";
const FIXTURE_TOKEN = "rslv_ui_test_fixture_key_not_a_real_secret";

test("buyer opens My cases with Google even when email delivery is disabled", async ({ page }) => {
  test.skip(process.env.RESOLVE_UI_GOOGLE_FIXTURE !== "1", "Requires the isolated Google OIDC simulation");
  const invite = await page.request.post(fixture + "/resolution-cases/intake-invites", {
    headers: { Authorization: "Bearer " + FIXTURE_TOKEN },
    data: { order_reference: "BROWSER-GOOGLE-1", customer_email: "buyer@gmail.com", send_email: false },
  });
  expect(invite.status()).toBe(201);
  const issued = await invite.json();
  expect(issued.email_queued).toBe(false);
  const intake = await page.request.post(fixture + "/customer-portal/intake", {
    data: { token: issued.token, issue_type: "missing_item", description: "Fixture buyer requested help." },
  });
  expect(intake.ok()).toBe(true);
  await page.route("https://accounts.google.com/o/oauth2/v2/auth?*", async (route) => {
    const auth = new URL(route.request().url());
    expect(auth.searchParams.get("scope")).toBe("openid email");
    const approval = await page.request.post(fixture + "/__ui_fixture_google_consent", {
      data: Object.fromEntries(auth.searchParams),
    });
    expect(approval.ok()).toBe(true);
    const callback = new URL(auth.searchParams.get("redirect_uri")!);
    callback.searchParams.set("code", (await approval.json()).code);
    callback.searchParams.set("state", auth.searchParams.get("state")!);
    await route.fulfill({ status: 302, headers: { location: callback.href } });
  });
  await page.goto("/customer/account");
  await expect(page.getByRole("button", { name: "Sign in with Google" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Email me a sign-in link" })).toHaveCount(0);
  await page.getByRole("button", { name: "Sign in with Google" }).click();
  await expect(page).toHaveURL(/\/customer\/account$/);
  await expect(page.getByText(/BROWSER-GOOGLE-1/)).toBeVisible();
  const cookies = await page.context().cookies();
  expect(cookies.find(cookie => cookie.name === "resolve_customer_session")?.httpOnly).toBe(true);
  expect(cookies.some(cookie => cookie.name === "resolve_google_flow")).toBe(false);
  expect((await page.request.get("/api/session")).status()).toBe(200);
  expect((await (await page.request.get("/api/session")).json()).merchant).toBeNull();
  await page.getByRole("button", { name: "Open case" }).click();
  await expect(page.getByText("Fixture buyer requested help.")).toBeVisible();
});
