import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import { once } from "node:events";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { createInterface } from "node:readline";
import { test } from "node:test";
import { setTimeout as delay } from "node:timers/promises";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";
import { expect } from "@playwright/test";
import { ResolveClient } from "@resolve-paypal/sdk";

const shop = fileURLToPath(new URL("../", import.meta.url));
const backend = fileURLToPath(new URL("../../../backend/", import.meta.url));
const fixture = fileURLToPath(new URL("../../../sdk/typescript/test/fixture.py", import.meta.url));
const simulated = process.env.RESOLVE_RUN_CHECKOUT_STORE_SIMULATION === "1";
const cleanEnv = Object.fromEntries(Object.entries(process.env)
  .filter(([name]) => !/^(RESOLVE_|SHOP_)/i.test(name)));

async function resources(t) {
  const scratch = await mkdtemp(join(tmpdir(), "field-brew-checkout-"));
  const stack = [];
  t.after(async () => {
    try { for (const cleanup of stack.reverse()) await cleanup(); }
    finally {
      const absolute = resolve(scratch);
      assert.equal(dirname(absolute), resolve(tmpdir()));
      assert.match(absolute.slice(dirname(absolute).length + 1), /^field-brew-checkout-[A-Za-z0-9]+$/);
      await rm(absolute, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
    }
  });
  return { scratch, stack };
}

async function start(stack, binary, args, options) {
  const child = spawn(binary, args, { ...options, stdio: ["ignore", "pipe", "pipe"], windowsHide: true });
  const stopped = once(child, "close");
  const lines = createInterface({ input: child.stdout });
  let errors = "";
  child.stderr.on("data", chunk => { errors = (errors + chunk).slice(-2200); });
  stack.push(async () => {
    lines.close();
    if (child.exitCode === null && child.signalCode === null) child.kill();
    await stopped;
  });
  try {
    return (await Promise.race([
      once(lines, "line", { signal: AbortSignal.timeout(35_000) }),
      stopped.then(() => { throw new Error("Test server exited: " + errors); }),
    ]))[0];
  } catch (error) {
    throw new Error("Test server did not start: " + errors, { cause: error });
  }
}

async function ready(base, route) {
  const end = performance.now() + 20_000;
  while (performance.now() < end) {
    const ok = await fetch(base + route, { signal: AbortSignal.timeout(1_500) }).then(r => r.ok, () => false);
    if (ok) return;
    await delay(200);
  }
  throw new Error("Test service was not healthy: " + route);
}

async function store(scratch, stack, env = {}) {
  const line = await start(stack, process.execPath, ["src/server.mjs"], {
    cwd: shop, env: { ...cleanEnv, SHOP_PORT: "0", SHOP_DATABASE_PATH: join(scratch, "store.sqlite3"), ...env },
  });
  assert.match(line, /^Field Brew Supply: http:\/\/127\.0\.0\.1:\d+$/);
  const base = line.slice("Field Brew Supply: ".length);
  await ready(base, "/api/catalog");
  return base;
}

async function resolveBackend(scratch, stack) {
  const runtime = spawnSync("uv", ["run", "--no-sync", "python", "-c", "import sys; print(sys.executable)"], {
    cwd: backend, encoding: "utf-8", env: cleanEnv, timeout: 25_000, windowsHide: true,
  });
  assert.equal(runtime.status, 0, "Sync backend dependencies before running the simulation.");
  const line = await start(stack, runtime.stdout.trim(), [fixture, join(scratch, "resolve.sqlite3"), "--paypal-simulation"], {
    cwd: backend, env: cleanEnv,
  });
  const keys = JSON.parse(line);
  const base = "http://127.0.0.1:" + keys.port;
  await ready(base, "/health");
  return { base, ...keys };
}

async function browser(stack, viewport = { width: 1180, height: 900 }) {
  const channel = process.env.SHOP_TEST_BROWSER_CHANNEL;
  const browser = await chromium.launch(channel ? { channel } : {});
  stack.push(() => browser.close());
  const context = await browser.newContext({ viewport });
  return { context, page: await context.newPage(), browser };
}

test("six products, cart totals and a useful mobile catalog preview", { timeout: 70_000 }, async (t) => {
  const { scratch, stack } = await resources(t);
  const base = await store(scratch, stack);
  const { page } = await browser(stack, { width: 390, height: 844 });
  await page.goto(base);
  await expect(page.locator(".product")).toHaveCount(6);
  await expect(page.getByRole("heading", { name: /Good coffee/ })).toBeVisible();
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth), 390);
  await page.getByRole("button", { name: "Add Camp Cup to cart" }).click();
  await page.getByRole("button", { name: "Cart 1" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.getByRole("button", { name: "Add one Camp Cup" }).click();
  await expect(page.locator("#cart-total")).toHaveText("$28.00");
  await expect(page.getByRole("button", { name: /Continue to PayPal/ })).toBeDisabled();
  await page.getByRole("button", { name: "Remove one Camp Cup" }).click();
  await expect(page.locator("#cart-total")).toHaveText("$14.00");
});

test("browser checkout captures once, connects the SDK and shows an external refund discrepancy", {
  timeout: 100_000, skip: !simulated,
}, async (t) => {
  assert.match(process.env.HTTPS_PROXY || "", /^http:\/\/127\.0\.0\.1:\d+\/?$/);
  assert.ok(process.env.NODE_EXTRA_CA_CERTS && process.env.NODE_USE_ENV_PROXY === "1",
    "Use Postman --proxy --lift with Node's environment proxy support enabled.");
  const { scratch, stack } = await resources(t);
  const evidence = await resolveBackend(scratch, stack);
  const supportResponse = await fetch(evidence.base + "/platform/support-keys", { method: "POST", headers: { Authorization: "Bearer " + evidence.key, "Content-Type": "application/json" }, body: JSON.stringify({ source: "field-brew-store" }) });
  assert.equal(supportResponse.status, 201);
  const supportKey = (await supportResponse.json()).api_key;

  const base = await store(scratch, stack, {
    SHOP_PAYPAL_CLIENT_ID: "simulation-client",
    SHOP_PAYPAL_CLIENT_SECRET: "simulation-secret",
    SHOP_PAYPAL_MERCHANT_ID: "SIMSELLER001",
    RESOLVE_API_URL: evidence.base,
    RESOLVE_API_KEY: supportKey,
  });
  const { page, browser: instance } = await browser(stack);
  const merchant = new ResolveClient({ baseUrl: evidence.base, apiKey: evidence.key });
  const control = async (path, data) => {
    const reply = await fetch("https://api-m.sandbox.paypal.com/__resolve_test/" + path, {
      method: data ? "POST" : "GET", redirect: "error",
      headers: { Authorization: "Bearer simulation-access-token", "Content-Type": "application/json" },
      body: data ? JSON.stringify(data) : undefined,
    });
    assert.ok(reply.ok, "Mock fixture operation failed: " + reply.status);
    return reply.json();
  };

  let paypalOrder;
  await page.route("https://www.sandbox.paypal.com/**", async (route) => {
    paypalOrder = new URL(route.request().url()).searchParams.get("token");
    const before = await control("shop/state/" + paypalOrder);
    assert.equal(before.capture_creations, 0);
    const approved = await control("shop/approve/" + paypalOrder, {});
    await route.fulfill({ status: 302, headers: { location: approved.return_url } });
  });
  await page.goto(base);
  await expect(page.locator(".product")).toHaveCount(6);
  const invalid = await page.request.post(base + "/api/orders", {
    data: { requestId: "11111111-1111-1111-1111-111111111111", items: [{ id: "cup", quantity: 1, cents: 1 }] },
  });
  assert.equal(invalid.status(), 400);
  if (process.env.SHOP_TEST_SCREENSHOT) await page.screenshot({ path: process.env.SHOP_TEST_SCREENSHOT, fullPage: true });

  await page.getByRole("button", { name: "Add Camp Cup to cart" }).click();
  await page.getByRole("button", { name: "Add Brew Brush to cart" }).click();
  await page.getByRole("button", { name: "Cart 2" }).click();
  await expect(page.locator("#cart-total")).toHaveText("$22.00");
  await page.getByRole("button", { name: /Continue to PayPal/ }).click();
  await expect(page.getByRole("heading", { name: "Payment confirmed" })).toBeVisible({ timeout: 32_000 });
  await expect(page.getByText("Matched PayPal", { exact: true })).toBeVisible();
  const receiptId = new URL(page.url()).searchParams.get("order");
  const receiptRoute = base + "/api/orders/" + receiptId;
  const receipt = await (await page.request.get(receiptRoute)).json();
  assert.equal(receipt.total, "22.00");
  assert.equal(receipt.comparison.checks.length, 6);
  assert.ok(receipt.comparison.checks.every(item => item.status === "match"));

  const [replay, second] = await Promise.all([
    page.request.post(receiptRoute + "/capture", { data: { token: paypalOrder } }),
    page.request.post(receiptRoute + "/capture", { data: { token: paypalOrder } }),
  ]);
  assert.equal((await replay.json()).caseId, receipt.caseId);
  assert.equal((await second.json()).caseId, receipt.caseId);
  const wrongToken = await page.request.post(receiptRoute + "/capture", { data: { token: "MISMATCH" } });
  assert.equal(wrongToken.status(), 409);
  const other = await instance.newContext();
  await other.request.get(base + "/");
  assert.equal((await other.request.get(receiptRoute)).status(), 404);
  assert.equal((await other.request.post(receiptRoute + "/capture", { data: { token: paypalOrder } })).status(), 404);

  const captured = await control("shop/state/" + paypalOrder);
  assert.equal(captured.capture_posts, 1);
  assert.equal(captured.capture_creations, 1);
  const first = await merchant.getEvidenceBundle(receipt.caseId);
  assert.equal(first.commerce.status, "match");
  assert.deepEqual(first.commerce.app.items.map(item => item.product_id), ["cup", "brush"]);
  assert.equal(first.case.evidence_summary.captured_amount, "22.00");
  await control("external/" + captured.capture_id, { cents: 500, status: "COMPLETED" });
  await page.getByRole("button", { name: "Check again" }).click();
  await expect(page.getByText("Difference found", { exact: true })).toBeVisible({ timeout: 28_000 });
  await expect(page.getByText("Refunded amount: mismatch (store 0.00; PayPal 5.00)")).toBeVisible();
  assert.equal((await merchant.getEvidenceBundle(receipt.caseId)).case.evidence_summary.provider_completed_amount, "5.00");
  assert.equal((await control("shop/state/" + paypalOrder)).capture_posts, 1);
  assert.equal((await control("state/" + captured.capture_id)).refund_posts, 0);

  // The same order page now handles an actual aftercare task, not just order syncing.
  await page.getByRole("textbox", { name: "Tell us what happened" }).fill("The cup handle arrived broken.");
  await page.getByRole("button", { name: "Send support request", exact: true }).click();
  await expect(page.locator("#support-progress")).toContainText("Your request is with the support team");
  await page.getByRole("button", { name: "Send support request", exact: true }).click();
  await expect(page.locator("#support-progress")).toContainText("Your request is with the support team");
  const status = await page.request.post(receiptRoute + "/resolution", { data: {} });
  assert.equal(status.status(), 200);
  const resolution = await status.json();
  assert.equal(resolution.issue_count, 1);
  assert.equal(resolution.refund.completed_amount, "5.00");
  assert.equal(resolution.refund.verification, "current");
  await page.getByRole("button",{name:"Where is my refund?",exact:true}).click();
  await expect(page.locator("#support-detail")).toContainText("Posting to your original payment method can take additional time");
  await page.getByRole("button",{name:"Check return options",exact:true}).click();
  await expect(page.locator("#support-detail")).toContainText("merchant will confirm eligibility, shipping costs and any applicable fees");
  await page.getByRole("button",{name:"View previous report",exact:true}).click();
  await expect(page.locator("#support-detail")).toContainText("The cup handle arrived broken.");

  assert.equal((await other.request.post(receiptRoute + "/resolution", { data: {} })).status(), 404);
  const supportLink = await page.request.post(receiptRoute + "/support-link", { data: {} });
  assert.equal(supportLink.status(), 201);
  const customer = await fetch(evidence.base + "/customer-portal/view", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token: (await supportLink.json()).token }) });
  assert.equal(customer.status, 200);
  assert.equal((await customer.json()).messages.filter(m => m.body === "The cup handle arrived broken.").length, 1);

  if (process.env.SHOP_TEST_RECEIPT_SCREENSHOT) {
    await page.screenshot({ path: process.env.SHOP_TEST_RECEIPT_SCREENSHOT, fullPage: true });
  }

});
