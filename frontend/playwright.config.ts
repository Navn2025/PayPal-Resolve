import { defineConfig } from "@playwright/test";

// Playwright's local readiness checks should never use the provider proxy.
process.env.NO_PROXY = [process.env.NO_PROXY, "127.0.0.1", "localhost"].filter(Boolean).join(",");
process.env.no_proxy = process.env.NO_PROXY;

export default defineConfig({
  testDir: "./tests",
  workers: 1,
  timeout: 45_000,
  expect: { timeout: 10_000 },
  use: {
    baseURL: "http://127.0.0.1:3100",
    viewport: { width: 1440, height: 900 },
    launchOptions: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE
      ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE } : {},
  },
  webServer: [
    {
      command: "uv --directory ../backend run python ../frontend/tests/fixture_backend.py",
      url: "http://127.0.0.1:8011/openapi.json",
      timeout: 45_000,
    },
    {
      command: "npm run dev -- --port 3100",
      url: "http://127.0.0.1:3100",
      timeout: 45_000,
      env: { RESOLVE_BACKEND_URL: "http://127.0.0.1:8011", RESOLVE_UI_TEST_SERVER: "1" },
    },
  ],
});
