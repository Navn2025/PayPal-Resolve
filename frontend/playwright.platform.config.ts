import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./tests", testMatch: ["platform.spec.ts", "platform.performance.spec.ts"], workers: 1, timeout: 300000,
  expect: { timeout: 20000 },
  use: { actionTimeout: 30000, baseURL: "http://127.0.0.1:3125", viewport: { width: 1440, height: 1000 },
    launchOptions: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE } : {} },
  webServer: [
    { command: "..\\backend\\.venv\\Scripts\\python.exe ..\\backend\\scripts\\isolated.py tests/platform-fixture.py", url: "http://127.0.0.1:8025/health", timeout: 60000 },
    { command: "node tests/isolated-next.mjs --port=3125 --backend-port=8025" + (process.env.RESOLVE_UI_PRODUCTION_TEST === "1" ? " --production" : ""), url: "http://127.0.0.1:3125", timeout: 360000 },
  ],
});
