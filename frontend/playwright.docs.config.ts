import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests", testMatch: "documentation.spec.ts", workers: 1, timeout: 60000,
  expect: { timeout: 15000 },
  use: { baseURL: "http://127.0.0.1:3133", viewport: { width: 1440, height: 1000 } },
  webServer: {
    command: "node tests/isolated-next.mjs --production --port=3133 --backend-port=8999",
    url: "http://127.0.0.1:3133/docs", timeout: 120000,
  },
});
