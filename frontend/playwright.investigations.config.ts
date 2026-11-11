import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests", testMatch: ["investigations.spec.ts", "promise-health.spec.ts", "settings.spec.ts"], workers: 1, timeout: 60000,
  expect: { timeout: 15000 },
  use: { baseURL: "http://127.0.0.1:3107", viewport: { width: 1440, height: 900 } },
  webServer: process.env.RESOLVE_AI_UI_EXTERNAL_SERVERS === "1" ? undefined : [
    { command: "..\\backend\\.venv\\Scripts\\python.exe ..\\backend\\scripts\\isolated.py tests/fixture_backend.py", url: "http://127.0.0.1:8011/openapi.json", timeout: 60000 },
    { command: "node tests/isolated-next.mjs" + (process.env.RESOLVE_UI_PRODUCTION_TEST === "1" ? " --production" : ""), url: "http://127.0.0.1:3107", timeout: 120000 },
  ],
});
