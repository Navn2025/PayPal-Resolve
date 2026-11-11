import { privateFixture } from "./helpers";
import { expect, test } from "@playwright/test";

const fixtureKey = "rslv_ui_test_fixture_key_not_a_real_secret";

test("settings uses the workspace shell with separate cards, one sign out and a code copy button", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.goto("/login?next=settings");
  await page.getByLabel("Resolve access key").fill(fixtureKey);
  await page.getByRole("button", { name: "Sign in with access key" }).click();
  await expect(page.getByRole("heading", { name: "Account settings", level: 1 })).toBeVisible();

  // Same shell as the workspace: sidebar with Settings active, breadcrumb, top-bar actions.
  const crumb = page.getByRole("navigation", { name: "Breadcrumb" });
  await expect(crumb).toHaveText(/Workspace\s*Settings/);
  await expect(page.getByRole("complementary", { name: "Workspace navigation" }).getByRole("link", { name: "Settings" })).toHaveAttribute("aria-current", "page");
  await expect(page.getByRole("button", { name: "Sign out" })).toHaveCount(1);

  // Account, PayPal sign-in and SDK keys are separate cards with status pills.
  for (const name of ["Workspace Test Shop", "PayPal sign-in", "SDK keys"]) {
    await expect(page.locator(".settings-section").filter({ has: page.getByRole("heading", { name, exact: true }) })).toHaveCount(1);
  }
  await expect(page.locator(".settings-section").first().locator(".badge")).toHaveText("Signed in");
  const capabilities = await (await page.request.get("/api/session")).json();
  await expect(page.locator(".settings-section").nth(1).locator(".badge").last()).toHaveText(capabilities.paypal_enabled ? (capabilities.paypal_linked ? "Linked" : "Ready to link") : "Not configured");

  await page.getByRole("button", { name: "Copy example code" }).click();
  await expect(page.getByText("Example code copied.")).toBeVisible();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toContain("createResolve().syncOrder");

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("heading", { name: "Account settings", level: 1 })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);

  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login$/);
});

test("conversation times are shown in the viewer's local time zone", async ({ browser, request }) => {
  const fixture = await privateFixture(request);
  await request.post(`http://127.0.0.1:8011/resolution-cases/${fixture.caseId}/customer-messages`, { headers: fixture.headers, data: { body: "Time zone check", request_id: crypto.randomUUID() } });
  for (const timezoneId of ["Asia/Kolkata", "America/New_York"]) {
    const context = await browser.newContext({ timezoneId, locale: "en-US" });
    try {
      const page = await context.newPage();
      await page.goto("/customer#" + fixture.token);
      const time = page.locator(".conversation-list time").first();
      await expect(time).toBeVisible();
      const stamp = await time.getAttribute("datetime");
      const expected = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZone: timezoneId })
        .format(new Date(stamp!));
      await expect(time).toHaveText(expected);
      await expect(time).not.toContainText("UTC");
    } finally { await context.close(); }
  }
});
