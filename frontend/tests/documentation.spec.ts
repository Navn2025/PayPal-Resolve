import { expect, test } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import content from "../content/docs.json";

test("public documentation works without an API and exports complete portable references", async ({ page, request, context }) => {
  const apiCalls: string[] = [];
  page.on("request", req => { if (new URL(req.url()).pathname.startsWith("/api/")) apiCalls.push(req.url()); });
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.goto("/");
  await page.getByRole("navigation", { name: "Main navigation" }).getByRole("link", { name: "Docs", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1 })).toContainText("From an issue");
  for (const article of content.articles) {
    await page.goto("/docs/" + article.slug);
    await expect(page.getByRole("heading", { level: 1, name: article.title, exact: true })).toBeVisible();
    for (const section of article.sections) await expect(page.locator("#" + section.id)).toHaveCount(1);
  }
  const guide = await request.get("/docs/resolve-guide.md");
  expect(guide.status()).toBe(200);
  const markdown = await guide.text();
  for (const article of content.articles) expect(markdown).toContain("## " + article.title);
  const schema = await request.get("/docs/resolve.openapi.json");
  expect(schema.status()).toBe(200);
  expect((await schema.json()).paths["/aftercare/issues"]).toBeTruthy();
  expect((await request.get("/docs/not-a-guide")).status()).toBe(404);

  await page.goto("/docs/sdk-integration");
  const source = page.locator(".docs-code").first();
  await source.getByRole("button", { name: "Copy code", exact: true }).click();
  await expect(source.getByRole("status")).toHaveText("Code copied to clipboard.");
  expect(await page.evaluate(() => navigator.clipboard.readText())).toContain("npm pack");
  await page.getByRole("searchbox", { name: "Search guides" }).fill("SMTP");
  await expect(page.getByRole("navigation", { name: "Guides" }).getByRole("link")).toHaveCount(1);
  await page.getByRole("navigation", { name: "Guides" }).getByRole("link", { name: "Connect supported services" }).click();
  await page.getByRole("searchbox", { name: "Search guides" }).fill("no-such-guide-xyz");
  await expect(page.getByRole("status").filter({ hasText: "No matching guide" })).toBeVisible();
  await page.getByRole("searchbox", { name: "Search guides" }).fill("");
  await page.goto("/docs/sdk-integration#register");
  await expect(page.getByRole("navigation", { name: "Guides" }).getByRole("link", { name: "Integrate the SDK" })).toHaveAttribute("aria-current", "page");
  await page.evaluate(() => window.scrollTo(0, 0));
  await mkdir("../.local/ui/docs-artifacts", { recursive: true });
  await page.screenshot({ path: "../.local/ui/docs-artifacts/sdk-desktop.png", fullPage: true });
  for (const width of [390, 320]) {
    await page.setViewportSize({ width, height: 844 });
    await page.getByLabel("Browse the guide").selectOption("sdk-integration");
    await expect(page.getByRole("heading", { level: 1, name: "Integrate the SDK" })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
  }
  await page.screenshot({ path: "../.local/ui/docs-artifacts/sdk-mobile.png", fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(page.getByRole("navigation", { name: "Main navigation" }).getByRole("link", { name: "Docs", exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
  expect(apiCalls).toEqual([]);
});
