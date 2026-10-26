/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The API answers the refresh-cookie routes only for its own origin; locally that is
// http://localhost:5173 (`_LOCAL_ORIGIN` in api_auth.py), so dev and preview both serve
// here and proxy /api to `make run-api` on :8000.
const api = { "/api": "http://localhost:8000" };

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, strictPort: true, proxy: api },
  preview: { port: 5173, strictPort: true, proxy: api },
  test: {
    environment: "jsdom",
    include: ["tests/unit/**/*.test.{ts,tsx}"],
    setupFiles: ["tests/unit/setup.ts"],
  },
});
