// Playwright config. The app must already be running (scripts/e2e.sh starts it):
//   JAM_URL=http://127.0.0.1:8765 npx playwright test
import { defineConfig, devices } from "@playwright/test";

const EVID = process.env.JAM_EVIDENCE || "../docs/evidence/e2e";
// Chromium: a fake microphone (a beep) so the in-browser recording can be tested end to end.
const CHROMIUM_ARGS = ["--autoplay-policy=no-user-gesture-required", "--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"];
export default defineConfig({
  testDir: "./tests",
  timeout: 15 * 60_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  outputDir: `${EVID}/artifacts`,
  reporter: [["list"], ["json", { outputFile: `${EVID}/results.json` }]],
  use: {
    baseURL: process.env.JAM_URL || "http://127.0.0.1:8765",
    trace: "retain-on-failure",
    actionTimeout: 30_000,
    navigationTimeout: 60_000,
    video: "on",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "webkit-iphone", use: { ...devices["iPhone 13"], browserName: "webkit" } },
    { name: "chromium-iphone", use: { ...devices["iPhone 13"], browserName: "chromium", launchOptions: { args: CHROMIUM_ARGS } } },
    { name: "chromium-desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1366, height: 860 }, launchOptions: { args: CHROMIUM_ARGS } } },
  ],
});
