import { defineConfig } from "@playwright/test";

const scenario = process.env.RESOLVE_AUDIT_SCENARIO ?? "";
process.env.NO_PROXY = [process.env.NO_PROXY, "127.0.0.1", "localhost"].filter(Boolean).join(",");
process.env.no_proxy = process.env.NO_PROXY;
if (scenario === "paypal-email") {
  process.env.RESOLVE_UI_PAYPAL_SIMULATION = "1";
  process.env.RESOLVE_UI_PAYPAL_LOGIN = "1";
  process.env.RESOLVE_UI_EMAIL_FIXTURE = "1";
}
if (scenario === "google") process.env.RESOLVE_UI_GOOGLE_FIXTURE = "1";

// Audit the compiled application without reading the owner's dotenv or database.
export default defineConfig({
  testDir: "./tests",
  testIgnore: ["platform*.spec.ts", "documentation.spec.ts"],
  workers: 1, timeout: 60000, expect: { timeout: 15000 },
  reporter: [["list"], ["json", { outputFile: process.env.RESOLVE_AUDIT_REPORT ?? "../.local/audit/browser-results.json" }]],
  use: { browserName: process.env.RESOLVE_AUDIT_BROWSER === "firefox" ? "firefox" : "chromium", baseURL: "http://127.0.0.1:3100", viewport: { width: 1440, height: 1000 }, screenshot: "only-on-failure", trace: "retain-on-failure" },
  webServer: [
    { command: "..\\backend\\.venv\\Scripts\\python.exe ..\\backend\\scripts\\isolated.py tests/audit-fixture.py " + scenario, url: "http://127.0.0.1:8011/openapi.json", timeout: 60000 },
    { command: "node tests/isolated-next.mjs --production --port=3100", url: "http://127.0.0.1:3100", timeout: 360000 },
  ],
});
