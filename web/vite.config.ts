/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The API answers the refresh-cookie routes only for its own origin; locally that is
// http://localhost:5173 (`_LOCAL_ORIGINS` in api_auth.py), so dev and preview both serve
// here and proxy /api to `make run-api` on :8000.
// The demo containers set API_URL (http://api:8000); everyone else uses the local API.
const api = { "/api": process.env.API_URL ?? "http://localhost:8000" };

export default defineConfig({
  plugins: [react()],
  // No data: URIs: the CDN's CSP (default-src 'self') would block an inlined font subset.
  build: { assetsInlineLimit: 0 },
  server: { port: 5173, strictPort: true, proxy: api },
  preview: { port: 5173, strictPort: true, proxy: api },
  test: {
    environment: "jsdom",
    include: ["tests/unit/**/*.test.{ts,tsx}"],
    setupFiles: ["tests/unit/setup.ts"],
    testTimeout: 15_000, // a busy runner needs room; a passing test still finishes at once
  },
});
