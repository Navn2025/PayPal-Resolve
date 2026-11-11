import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "../.local/production-video", testMatch: "capture.spec.ts", workers: 1,
  timeout: 300000, expect: { timeout: 20000 },
  reporter: [["list"], ["json", { outputFile: "../.local/production-video/capture-results.json" }]],
  use: { actionTimeout: 25000, baseURL: "http://127.0.0.1:3125", viewport: { width: 1440, height: 900 }, screenshot: "only-on-failure" },
  webServer: [
    { command: "..\\backend\\.venv\\Scripts\\python.exe ..\\backend\\scripts\\isolated.py tests/platform-fixture.py", url: "http://127.0.0.1:8025/health", timeout: 60000 },
    { command: "node tests/isolated-next.mjs --production --port=3125 --backend-port=8025", url: "http://127.0.0.1:3125", timeout: 360000 },
  ],
});
