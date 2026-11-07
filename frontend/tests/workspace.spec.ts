import { expect, test, type Page } from "@playwright/test";

const FIXTURE_TOKEN = "rslv_ui_test_fixture_key_not_a_real_secret";
function openFixtureLink(page: Page, link: string) {
  const publicLink = new URL(link);
  return new URL(publicLink.pathname + publicLink.hash, page.url()).href;
}

async function approve(page: Page) {
  await page.getByRole("button", { name: "Review refund", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Decision note").fill("Approve the confirmed outstanding amount.");
  await dialog.getByRole("button", { name: "Approve $20.00", exact: true }).click();
  await expect(page.getByRole("button", { name: "Review submission" })).toBeVisible();
}

async function connect(page: Page) {
  await page.getByRole("button", { name: "Connect account" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Merchant key").fill(FIXTURE_TOKEN);
  await dialog.getByRole("button", { name: "Connect account" }).click();
  await expect(page.getByText("Connected · Sandbox")).toBeVisible();
  await expect(page.getByRole("button", { name: /Connected refund fixture/ })).toBeVisible();
}

async function confirmWarehouse(page: Page, note: string) {
  await page.locator(".promise-row summary").filter({ hasText: "Return milestone" }).click();
  await page.getByRole("button", { name: "Record evidence" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Internal milestone").selectOption("confirmed");
  await dialog.getByLabel("Evidence note").fill(note);
  await dialog.getByRole("button", { name: "Save evidence" }).click();
  await expect(dialog).not.toBeVisible();
}

test("order invite opens a buyer issue and evidence appears in the merchant inbox", async ({ page, browser }, info) => {
  await page.goto("/demo");
  await connect(page);
  await page.getByRole("button", { name: "Invite customer" }).click();
  const invite = page.getByRole("dialog");
  await invite.getByLabel("Order reference").fill("BROWSER-ORDER-INTAKE");
  await invite.getByRole("button", { name: "Create intake link" }).click();
  await expect(invite.getByLabel("Private intake link")).toHaveValue(/#rint_/);
  const link = await invite.getByLabel("Private intake link").inputValue();
  await invite.getByRole("button", { name: "Close dialog" }).click();

  const visitor = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  try {
    const buyer = await visitor.newPage();
    await buyer.goto(openFixtureLink(page, link));
    await expect(buyer.getByRole("heading", { name: "Request help with your order" })).toBeVisible();
    await expect(buyer.getByText("BROWSER-ORDER-INTAKE")).toBeVisible();
    await buyer.getByLabel("What happened?").selectOption("damaged_delivery");
    await buyer.getByLabel("Describe the issue").fill("The lamp arrived with a cracked shade.");
    await buyer.getByRole("button", { name: "Submit support request" }).click();
    await expect(buyer.getByText("Request received", { exact: true })).toBeVisible();
    await expect(buyer.getByText("Waiting on merchant", { exact: true })).toBeVisible();
    await buyer.locator('input[type="file"]').setInputFiles({
      name: "return-slip.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.7\nTest receipt\n"),
    });
    await buyer.getByRole("button", { name: "Upload evidence" }).click();
    await expect(buyer.getByRole("button", { name: "Download return-slip.pdf" })).toBeVisible();
    await expect(buyer.getByText(/Customer submitted ·/)).toBeVisible();
    await buyer.screenshot({ path: info.outputPath("buyer-intake-case.png"), fullPage: true });

    await page.getByRole("button", { name: "Reload workspace" }).click();
    const caseRow = page.getByRole("button", { name: /BROWSER-ORDER-INTAKE/ });
    await expect(caseRow).toContainText("1 unread");
    await caseRow.click();
    await page.getByRole("button", { name: "Manage case" }).click();
    const triage = page.getByRole("dialog");
    await triage.getByLabel("Assignee").fill("Returns team");
    await triage.getByLabel("Case due date").fill("2000-01-02T12:00");
    await triage.getByLabel("Waiting on customer").check();
    await triage.getByRole("button", { name: "Save case settings" }).click();
    await expect(triage).toHaveCount(0);
    await page.getByRole("button", { name: "Waiting on customer", exact: true }).click();
    await expect(caseRow).toContainText("Returns team");
    await expect(caseRow).toContainText("Overdue");
    await page.getByRole("button", { name: "Customer portal", exact: true }).click();
    await expect(page.getByText("The lamp arrived with a cracked shade.")).toBeVisible();
    await expect(page.getByText(/Customer submitted ·/)).toBeVisible();
    const download = page.waitForEvent("download");
    await page.getByRole("button", { name: "Download return-slip.pdf" }).click();
    expect((await download).suggestedFilename()).toBe("return-slip.pdf");

    await buyer.getByRole("button", { name: "Refresh status" }).click();
    await expect(buyer.getByText("Your turn", { exact: true })).toBeVisible();
    await expect(buyer.getByText(/Overdue ·/)).toBeVisible();
    await buyer.getByLabel("Write a message").fill("I have uploaded the return slip.");
    await buyer.getByRole("button", { name: "Send message" }).click();
    await expect(buyer.getByText("I have uploaded the return slip.")).toBeVisible();
    await expect(buyer.getByText("Waiting on merchant", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Refresh messages" }).click();
    await expect(page.getByText("I have uploaded the return slip.")).toBeVisible();
    await expect(caseRow).toHaveCount(0);
    await page.getByRole("button", { name: "Unread", exact: true }).click();
    await expect(caseRow).toContainText("2 unread");
    await page.getByRole("button", { name: "Mark messages read" }).click();
    await expect(caseRow).toHaveCount(0);
  } finally { await visitor.close(); }
});

test("desktop demo shows the exact amount, then approves and submits separately", async ({ page }, info) => {
  await page.goto("/demo");
  await expect(page.getByRole("heading", { name: "Resolution workspace" })).toBeVisible();
  await expect(page.locator(".money-outstanding")).toContainText("$20.00");
  await expect(page.getByRole("button", { name: "Review refund", exact: true })).toBeEnabled();
  await page.screenshot({ path: info.outputPath("desktop-inbox.png"), fullPage: true });
  await approve(page);
  await expect(page.locator(".money-outstanding")).toContainText("$20.00");
  await page.getByRole("button", { name: "Review submission" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Submit demo refund" }).click();
  await expect(page.getByRole("heading", { name: "Refund promise fulfilled" })).toBeVisible();
  await expect(page.locator(".money-outstanding")).toContainText("$0.00");
  await page.getByRole("button", { name: "Buyer receipt" }).click();
  await expect(page.getByRole("article", { name: "Buyer receipt" })).toContainText("$30.00");
  await expect(page.getByRole("article", { name: "Buyer receipt" })).toContainText("No money moved");
  await expect(page.getByRole("article", { name: "Buyer receipt" })).not.toContainText("Support ticket");
  await page.emulateMedia({ media: "print" });
  await expect(page.getByRole("article", { name: "Buyer receipt" })).toBeVisible();
  await expect(page.getByRole("button", { name: "New case" })).not.toBeVisible();
});

test("outside demo refund invalidates the earlier approval and can be reset", async ({ page }) => {
  await page.goto("/demo");
  await approve(page);
  await page.getByRole("button", { name: "Simulate outside refund" }).click();
  await expect(page.getByText("Duplicate refund blocked.", { exact: false })).toBeVisible();
  await expect(page.getByRole("button", { name: "Review submission" })).toHaveCount(0);
  await page.getByRole("button", { name: "Evidence timeline" }).click();
  await expect(page.getByText("An external refund covered the remaining $20.00.", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: "Reset demo" }).click();
  await expect(page.locator(".money-outstanding")).toContainText("$20.00");
});

test("a smaller partial refund leaves the rest of the promise open", async ({ page }) => {
  await page.goto("/demo");
  await page.getByRole("button", { name: "Review refund", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Decision note").fill("Refund five dollars now.");
  await dialog.getByLabel("Refund amount (USD)").fill("20.01");
  await dialog.getByRole("button", { name: "Approve refund", exact: true }).click();
  await expect(dialog.getByRole("alert")).toContainText("between $0.01 and $20.00");
  await dialog.getByLabel("Refund amount (USD)").fill("5");
  await dialog.getByRole("button", { name: "Approve $5.00", exact: true }).click();
  await page.getByRole("button", { name: "Review submission" }).click();
  await dialog.getByRole("button", { name: "Submit demo refund" }).click();
  await expect(page.locator(".money-outstanding")).toContainText("$15.00");
  await expect(page.getByRole("heading", { name: "Review $15.00 refund" })).toBeVisible();
});

test("mobile inbox filters, opens a case and has no horizontal overflow", async ({ page }, info) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/demo");
  const search = page.getByRole("textbox", { name: "Search cases" });
  await search.fill("lamp");
  await expect(page.locator(".case-row")).toHaveCount(1);
  await page.getByRole("button", { name: /Replacement for damaged lamp/ }).click();
  await expect(page.getByRole("heading", { name: "Replacement for damaged lamp" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.screenshot({ path: info.outputPath("mobile-case.png"), fullPage: true });
  await page.getByRole("button", { name: "Back to inbox" }).click();
  await expect(search).toBeVisible();
});

test("connected UI uses FastAPI and stores evidence without exposing the merchant key", async ({ page }) => {
  await page.goto("/demo");
  expect((await page.request.get("/api/resolve/resolution-cases")).status()).toBe(401);
  await connect(page);
  const cookies = await page.context().cookies();
  expect(cookies.find((cookie) => cookie.name === "resolve_merchant_session")?.httpOnly).toBe(true);
  expect(JSON.stringify(cookies)).not.toContain(FIXTURE_TOKEN);
  expect(await page.evaluate(() => JSON.stringify([localStorage, sessionStorage]))).not.toContain(FIXTURE_TOKEN);
  expect((await page.request.post("/api/resolve/resolution-cases", {
    headers: { Origin: "https://example.invalid" }, data: { title: "blocked" },
  })).status()).toBe(403);
  await page.getByRole("button", { name: "New case", exact: true }).first().click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Case title").fill("Warehouse evidence browser test");
  await dialog.getByLabel("Order reference (optional)").fill("UI-TEST-ORDER");
  await dialog.getByRole("button", { name: "Create case" }).click();
  await expect(page.getByRole("heading", { name: "Warehouse evidence browser test" })).toBeVisible();
  await page.getByRole("button", { name: "Add promise" }).click();
  await dialog.getByLabel("Promise to the customer").fill("Confirm the returned parcel");
  await dialog.getByLabel("Return reference").fill("UI-RMA-2");
  await dialog.getByLabel("Source evidence").fill("Customer support record for this return.");
  await dialog.getByRole("button", { name: "Record promise" }).click();
  await expect(dialog).not.toBeVisible();
  await confirmWarehouse(page, "Warehouse recorded receipt under UI-RMA-2.");
  await expect(page.locator(".case-kicker")).toContainText("Fulfilled");
  await page.getByRole("button", { name: "Evidence timeline" }).click();
  await expect(page.getByText("Warehouse recorded receipt under UI-RMA-2.")).toBeVisible();
  await page.reload();
  await expect(page.getByText("Connected · Sandbox")).toBeVisible();
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("heading", { name: "Merchant sign in" })).toBeVisible();
});

test("connected refund uses real API routes and the isolated PayPal simulation", async ({ page, browser }) => {
  test.skip(process.env.RESOLVE_UI_PAYPAL_SIMULATION !== "1", "Requires local Postman PayPal TLS simulation");
  await page.goto("/demo");
  await connect(page);
  await page.getByRole("button", { name: /Connected refund fixture/ }).click();
  await page.getByRole("button", { name: "Customer portal", exact: true }).click();
  await page.getByRole("button", { name: "Create customer link" }).click();
  await expect(page.getByLabel("Private customer link")).toHaveValue(/#rsvp_/);
  const link = await page.getByLabel("Private customer link").inputValue();
  await page.getByRole("button", { name: "Overview", exact: true }).click();
  await expect(page.getByText("Complete the prerequisite promise before approving a refund.")).toBeVisible();
  await confirmWarehouse(page, "Warehouse confirmed the payment fixture return.");
  await page.getByRole("button", { name: "Refresh evidence" }).click();
  await expect(page.locator(".money-confirmed")).toContainText("$10.00");
  await expect(page.locator(".money-outstanding")).toContainText("$20.00");
  await page.getByRole("button", { name: "Needs approval", exact: true }).click();
  await expect(page.getByRole("button", { name: /Connected refund fixture/ })).toBeVisible();
  await approve(page);
  await page.getByRole("button", { name: "Review submission" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Submit Sandbox refund" }).click();
  await expect(page.getByRole("heading", { name: "Refund promise fulfilled" })).toBeVisible();
  await expect(page.locator(".money-confirmed")).toContainText("$30.00");
  await expect(page.locator(".money-outstanding")).toContainText("$0.00");
  const visitor = await browser.newContext();
  try {
    const buyer = await visitor.newPage();
    await buyer.goto(openFixtureLink(page, link));
    await expect(buyer.getByText("Return confirmed", { exact: true })).toBeVisible();
    await expect(buyer.getByText("Refund approved", { exact: true })).toBeVisible();
    await expect(buyer.getByText("PayPal confirmed a refund", { exact: true })).toBeVisible();
    await expect(buyer.getByText("No action needed", { exact: true })).toBeVisible();
  } finally { await visitor.close(); }
});

test("connected stale submission is rejected without a provider refund POST", async ({ page }) => {
  test.skip(process.env.RESOLVE_UI_PAYPAL_SIMULATION !== "1", "Requires local Postman PayPal TLS simulation");
  await page.goto("/demo");
  await connect(page);
  await page.getByRole("button", { name: /Outside refund fixture/ }).click();
  await confirmWarehouse(page, "Warehouse confirmed the return.");
  await page.getByRole("button", { name: "Refresh evidence" }).click();
  await expect(page.locator(".money-outstanding")).toContainText("$20.00");
  await approve(page);
  expect((await page.request.post("http://127.0.0.1:8011/__ui_fixture_outside_refund")).ok()).toBe(true);
  await page.getByRole("button", { name: "Review submission" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("button", { name: "Submit Sandbox refund" }).click();
  await expect(dialog.getByRole("alert")).toBeVisible();
  await dialog.getByRole("button", { name: "Close dialog" }).click();
  await expect(page.getByRole("heading", { name: "Refund promise fulfilled" })).toBeVisible();
  const stats = await (await page.request.get("http://127.0.0.1:8011/__ui_fixture_outside_stats")).json();
  expect(stats.refund_posts).toBe(0);
});

test("customer demo is separate and usable on mobile", async ({ page }, info) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/customer?demo=1");
  await expect(page.getByRole("heading", { name: "Your headphone return" })).toBeVisible();
  await expect(page.locator(".money-outstanding")).toContainText("$20.00");
  await expect(page.getByRole("button", { name: "Connect account" })).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.screenshot({ path: info.outputPath("customer-mobile.png"), fullPage: true });
  await page.getByLabel("Write a message").fill("Can you confirm the remaining amount?");
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(page.getByText("Can you confirm the remaining amount?")).toBeVisible();
});

test("email sign-in opens only the invited case and uses a customer cookie", async ({ page, browser }) => {
  test.skip(process.env.RESOLVE_UI_EMAIL_FIXTURE !== "1", "Requires the local email fixture");
  await page.goto("/demo");
  await connect(page);
  await page.getByRole("button", { name: "Invite customer" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Order reference").fill("BROWSER-EMAIL-ORDER");
  await dialog.getByLabel("Buyer email (optional)").fill("browser-buyer@example.com");
  await dialog.getByRole("button", { name: "Create intake link" }).click();
  await expect(dialog.getByText("Invite email queued for delivery.")).toBeVisible();
  const invite = await dialog.getByLabel("Private intake link").inputValue();
  const local = new URL(page.url()).origin;
  const visitor = await browser.newContext({ viewport: { width: 390, height: 844 } });
  try {
    const customer = await visitor.newPage();
    await customer.goto(local + "/customer" + new URL(invite).hash);
    await customer.getByLabel("What happened?").selectOption("missing_item");
    await customer.getByLabel("Describe the issue").fill("The order arrived without the spare part.");
    await customer.getByRole("button", { name: "Submit support request" }).click();
    await expect(customer.getByText("Request received", { exact: true })).toBeVisible();
    await customer.getByRole("link", { name: "My cases" }).click();
    await customer.getByLabel("Email address").fill("browser-buyer@example.com");
    await customer.getByRole("button", { name: "Email me a sign-in link" }).click();
    await expect(customer.getByText(/you’ll receive a sign-in link/)).toBeVisible();
    const { token } = await (await page.request.get("http://127.0.0.1:8011/__ui_fixture_login_token")).json();
    await customer.goto(local + "/customer/account#" + token);
    await customer.getByRole("button", { name: "Continue to My cases" }).click();
    await expect(customer.getByText(/BROWSER-EMAIL-ORDER/)).toBeVisible();
    await expect(customer.getByRole("button", { name: "Open case" })).toHaveCount(1);
    expect((await visitor.cookies()).find((c) => c.name === "resolve_customer_session")?.httpOnly).toBe(true);
    expect((await visitor.cookies()).some((c) => c.name === "resolve_merchant_session")).toBe(false);
    expect((await customer.request.get(local + "/api/resolve/resolution-cases")).status()).toBe(401);
    await customer.getByRole("button", { name: "Open case" }).click();
    await expect(customer.getByRole("heading", { name: "Missing item" })).toBeVisible();
    const grant = customer.url();
    await customer.getByRole("link", { name: "My cases" }).click();
    await customer.getByRole("button", { name: "Sign out" }).click();
    await customer.goto(grant);
    await expect(customer.getByRole("alert").filter({ hasText: "invalid, expired, or revoked" })).toBeVisible();
  } finally { await visitor.close(); }
});

test("an unauthenticated customer follows a private link, messages the merchant and loses access on revocation", async ({ page, browser }) => {
  await page.goto("/demo");
  await connect(page);
  await page.getByRole("button", { name: /Connected refund fixture/ }).click();
  await page.getByRole("button", { name: "Customer portal", exact: true }).click();
  await page.getByLabel("Customer heading").fill("Your return update");
  await page.getByLabel(/Show order reference/).check();
  await page.getByRole("button", { name: /^(Create|Replace) customer link$/ }).click();
  const linkField = page.getByLabel("Private customer link");
  await expect(linkField).toBeVisible();
  const link = await linkField.inputValue();
  expect(new URL(link).search).toBe("");
  expect(new URL(link).hash).toMatch(/^#rsvp_[A-Za-z0-9_-]{43}$/);

  const visitor = await browser.newContext({ viewport: { width: 390, height: 844 } });
  try {
    const customer = await visitor.newPage();
    await customer.goto(openFixtureLink(page, link));
    await expect(customer.getByRole("heading", { name: "Your return update" })).toBeVisible();
    await expect(customer.getByText("Order UI-TEST-ORDER")).toBeVisible();
    await expect(customer.getByText("Refund $30 after warehouse receipt")).toBeVisible();
    await expect(customer.getByText("Accepted return terms")).toHaveCount(0);
    expect((await visitor.cookies()).some((cookie) => cookie.name === "resolve_merchant_session")).toBe(false);
    expect((await customer.request.get(new URL("/api/resolve/resolution-cases", customer.url()).href)).status()).toBe(401);
    await customer.getByLabel("Write a message").fill("Could you tell me when the refund will arrive?");
    await customer.getByRole("button", { name: "Send message" }).click();
    await expect(customer.getByText("Could you tell me when the refund will arrive?")).toBeVisible();

    await page.getByRole("button", { name: "Refresh messages" }).click();
    await expect(page.getByText("Could you tell me when the refund will arrive?")).toBeVisible();
    await page.getByLabel("Reply to customer").fill("We are checking the warehouse receipt now.");
    await page.getByRole("button", { name: "Send message" }).click();
    await expect(page.getByText("We are checking the warehouse receipt now.")).toBeVisible();
    await customer.getByRole("button", { name: "Refresh messages" }).click();
    await expect(customer.getByText("We are checking the warehouse receipt now.")).toBeVisible();

    await page.getByRole("button", { name: "Revoke access" }).click();
    await expect(page.getByText("Customer access revoked.")).toBeVisible();
    await customer.getByRole("button", { name: "Refresh status" }).click();
    await expect(customer.getByRole("alert").filter({ hasText: "invalid, expired, or revoked" })).toBeVisible();
    await expect(customer.getByText("We are checking the warehouse receipt now.")).toHaveCount(0);
  } finally { await visitor.close(); }
});
