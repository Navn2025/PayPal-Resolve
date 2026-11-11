import { expect, test } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";
import content from "../content/docs.json";
import { resolve } from "node:path";
import { privateFixture, signInFixture } from "./helpers";

// Only the credential-free, provider-disabled QA run may publish manual captures.
const captureDirectory = resolve(__dirname, process.env.RESOLVE_CAPTURE_MANUAL === "1" && !process.env.RESOLVE_AUDIT_SCENARIO
  ? "../../docs/user-manual/screenshots" : "../../.local/integration-audit/browser-captures");

test("staff credentials cannot submit as URL parameters before hydration", async ({ browser, page }) => {
  const withoutScripts = await browser.newContext({ javaScriptEnabled: false });
  try {
    const initial = await withoutScripts.newPage();
    await initial.goto("/account");
    await expect(initial.locator("form")).toHaveAttribute("method", "post");
    await expect(initial.getByLabel("Password", { exact: true })).toBeDisabled();
    await expect(initial.getByRole("button", { name: "Sign in", exact: true }).last()).toBeDisabled();
  } finally { await withoutScripts.close(); }
  await page.goto("/account");
  await expect(page.getByLabel("Password", { exact: true })).toBeEnabled();
  await page.getByRole("button", { name: "Create workspace", exact: true }).first().click();
  await expect(page.getByRole("heading", { name: "Create your merchant workspace" })).toBeVisible();
  await page.getByLabel("Store or business name").fill("Readiness fixture");
  await page.getByLabel("Your name").fill("Fixture user");
  await page.getByLabel("Email", { exact: true }).fill("not-an-email");
  await page.getByLabel("Password", { exact: true }).fill("short");
  await page.getByRole("button", { name: "Create workspace", exact: true }).last().click();
  expect(await page.locator("form").evaluate((form: HTMLFormElement) => form.checkValidity())).toBe(false);
  expect(page.url()).not.toContain("password");
});

test("all real application pages render at desktop laptop tablet and mobile widths", async ({ page, context, request }) => {
  test.setTimeout(240000);
  const directory = captureDirectory;
  await mkdir(directory, { recursive: true });
  const failures: string[] = [], serverErrors: string[] = [], consoleErrors: string[] = [];
  const rejectedResponses: { path: string; status: number }[] = [];
  page.on("pageerror", error => failures.push(error.message));
  page.on("console", message => { if (message.type() === "error") consoleErrors.push(message.text()); });
  page.on("response", response => {
    const path = new URL(response.url()).pathname.replace(/[0-9a-f]{8}-[0-9a-f-]{27,}/g, "{id}");
    if (response.status() >= 500) serverErrors.push(response.status() + " " + path);
    if (response.status() >= 400) rejectedResponses.push({ path, status: response.status() });
  });
  const pages = [
    ["01-home", "/"], ["02-merchant-login", "/login"], ["03-account", "/account"],
    ["04-buyer-entry", "/customer"], ["05-buyer-account", "/customer/account"], ["08-docs", "/docs"],
    ...content.articles.map((article, index) => [`${String(index + 9).padStart(2, "0")}-guide-${article.slug}`, "/docs/" + article.slug]),
  ];
  const results: { page: string; width: number; milliseconds: number; screenshot: string }[] = [];
  async function capture(name: string, path: string, width: number) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
    const started = Date.now();
    // Force an actual document navigation when only the private fragment differs.
    await page.goto("about:blank");
    const response = await page.goto(path);
    expect(response?.status(), path.split("#")[0]).toBe(200);
    await expect(page.locator("main")).toBeVisible();
    if (path.startsWith("/workspace?") || path === "/workspace") await expect(page.getByRole("heading", { name: "Resolution workspace", exact: true })).toBeVisible();
    if (path === "/workspace/orders") await expect(page.getByRole("heading", { name: "Orders", exact: true })).toBeVisible();
    if (path === "/workspace/settings") await expect(page.getByRole("heading", { name: "SDK keys", exact: true })).toBeVisible();
    if (path === "/workspace/operations") await expect(page.getByText("Recorded refund balances", { exact: true })).toBeVisible();
    if (path.startsWith("/customer#")) await expect(page.getByRole("heading", { name: "Your order support", exact: true })).toBeVisible();
    await page.evaluate(() => document.fonts.ready);
    expect(await page.evaluate(() => document.documentElement.scrollWidth), path + " width " + width).toBeLessThanOrEqual(width);
    const filename = `${name}-${width}.png`;
    await page.screenshot({ path: directory + "/" + filename, fullPage: true });
    results.push({ page: path.split("#")[0], width, milliseconds: Date.now() - started, screenshot: filename });
  }
  for (const [name, path] of pages) for (const width of [1440, 1180, 768, 390]) await capture(name, path, width);
  await page.goto("/account");
  await page.getByRole("button", { name: "Create workspace", exact: true }).first().click();
  await page.screenshot({ path: directory + "/19-workspace-registration-390.png", fullPage: true });
  await page.goto("/login");
  await page.getByLabel("Resolve access key").fill("rslv_invalid_test_key_11111111");
  await page.getByRole("button", { name: "Sign in with access key" }).click();
  await expect(page.getByRole("region", { name: "Merchant sign in" }).getByRole("alert")).toBeVisible();
  await page.screenshot({ path: directory + "/20-login-error-390.png", fullPage: true });
  await signInFixture(page);
  for (const [name, path] of [["21-workspace", "/workspace"], ["22-orders", "/workspace/orders"], ["23-settings", "/workspace/settings"], ["24-operations", "/workspace/operations"]]) {
    for (const width of [1440, 1180, 768, 390]) await capture(name, path, width);
  }
  for (const tab of ["Missed promises", "Support imports", "Team", "Connections", "Audit"]) {
    await page.getByRole("navigation", { name: "Operations sections" }).getByRole("button", { name: tab, exact: true }).click();
    await expect(page.getByRole("status").filter({ hasText: /^Loading / })).toHaveCount(0);
    await page.screenshot({ path: directory + "/25-operations-" + tab.toLowerCase().replaceAll(" ", "-") + "-390.png", fullPage: true });
    expect(await page.evaluate(() => document.documentElement.scrollWidth), tab).toBeLessThanOrEqual(390);
  }
  const buyer = await privateFixture(request);
  for (const width of [1440, 1180, 768, 390]) await capture("07-buyer-case", "/customer#" + buyer.token, width);
  const scenario = process.env.RESOLVE_AUDIT_SCENARIO;
  await writeFile(resolve(__dirname, `../../.local/integration-audit/pages${scenario ? "-" + scenario : ""}.json`), JSON.stringify({ environment: scenario ? `actual compiled app and FastAPI; controlled ${scenario} provider stand-ins; not account-backed evidence` : "real compiled app and actual FastAPI; isolated QA database; providers disabled; not hosted production", results, failures, serverErrors, consoleErrors, rejectedResponses }, null, 2));
  expect(failures).toEqual([]); expect(serverErrors).toEqual([]);
  await context.clearCookies();
});

test("capture API-backed case dialogs timeline and receipt", async ({ page }) => {
  const directory = captureDirectory;
  await mkdir(directory, { recursive: true });
  await signInFixture(page);
  await page.getByRole("button", { name: /Connected refund fixture/ }).click();
  await page.getByRole("button", { name: "Evidence timeline", exact: true }).click();
  await page.screenshot({ path: directory + "/28-case-timeline-1440.png", fullPage: true });
  await page.getByRole("button", { name: "Buyer receipt", exact: true }).click();
  await page.screenshot({ path: directory + "/29-case-receipt-1440.png", fullPage: true });
  await page.getByRole("button", { name: "New case", exact: true }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.getByRole("dialog").screenshot({ path: directory + "/30-new-case-form.png" });
});
