import { defineConfig } from "@playwright/test";

// Runs against the built app on :5173 (vite preview, which proxies /api to the API on
// :8000). Start the API first, from the repo root, with PLATFORM_ENV=local so codes go
// to build/mail/outbox.jsonl (LocalFileMailer). CI: the `web-e2e` job.
export default defineConfig({
  testDir: "tests/e2e",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: { baseURL: "http://localhost:5173", trace: "retain-on-failure" },
  projects: [
    { name: "phone-360", use: { browserName: "chromium", viewport: { width: 360, height: 740 }, isMobile: true, hasTouch: true } },
    { name: "desktop-1280", use: { browserName: "chromium", viewport: { width: 1280, height: 800 } } },
  ],
  webServer: {
    command: "npx vite preview",
    url: "http://localhost:5173/signup",
    reuseExistingServer: !process.env.CI,
  },
});
