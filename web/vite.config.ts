/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import type { IncomingMessage, ServerResponse } from "node:http";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig, type Connect, type Plugin } from "vite";

// The API answers the refresh-cookie routes only for its own origin; locally that is
// http://localhost:5173 (`_LOCAL_ORIGINS` in api_auth.py), so dev and preview both serve
// here and proxy /api to `make run-api` on :8000.
// The demo containers set API_URL (http://api:8000); everyone else uses the local API.
const api = { "/api": process.env.API_URL ?? "http://localhost:8000" };

const here = dirname(fileURLToPath(import.meta.url));
const landing = resolve(here, "..", "landing");
const TYPES: Record<string, string> = { ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".woff2": "font/woff2" };

/**
 * Local development and preview only: show the Kartaa landing page (landing/, a separate static site) at "/" for a
 * visitor with no session, so http://localhost:5173/ opens it. Its Sign in and Sign up buttons go to /signin and /signup
 * in the app. A person who is signed in carries the `kartaa_in` hint cookie (set by the app, see auth/session.ts) and
 * gets the app at "/", which sends them to their home. The page's own stylesheet and fonts are served from the same
 * build. Production hosting of the landing page is separate and not set up here. The demo's nginx does the same job.
 */
function landingAtRoot(): Plugin {
  const dist = join(landing, "dist");
  const build = () => {
    // Rebuilt every time the server starts, so an edit to landing/site.config.json shows after a restart.
    try {
      execFileSync(process.execPath, [join(landing, "build.mjs")], { stdio: "pipe" });
    } catch (e) {
      console.warn("The landing page could not be built, so / shows the app instead:", (e as Error).message);
    }
  };
  const serve: Connect.NextHandleFunction = (req: IncomingMessage, res: ServerResponse, next) => {
    if ((req.method !== "GET" && req.method !== "HEAD") || !req.url) return next();
    const path = req.url.split("?")[0];
    let file: string | null = null;
    if (path === "/") {
      if (/(^|;\s*)kartaa_in=1(;|$)/.test(req.headers.cookie ?? "")) return next();
      file = "index.html";
    } else if (path === "/styles.css") file = "styles.css";
    else if (/^\/fonts\/[\w.-]+\.woff2$/.test(path)) file = path.slice(1);
    if (!file || !existsSync(join(dist, file))) return next();
    res.setHeader("Content-Type", TYPES[file.slice(file.lastIndexOf("."))] ?? "application/octet-stream");
    res.setHeader("Cache-Control", "no-cache");
    res.end(req.method === "HEAD" ? undefined : readFileSync(join(dist, file)));
  };
  return {
    name: "kartaa-landing-at-root",
    configureServer(server) {
      if (process.env.VITEST) return; // unit tests never need the landing page
      build();
      server.middlewares.use(serve);
    },
    configurePreviewServer(server) {
      build();
      server.middlewares.use(serve);
    },
  };
}

export default defineConfig({
  plugins: [react(), landingAtRoot()],
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
