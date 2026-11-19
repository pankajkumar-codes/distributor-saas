# Kartaa landing page

A static page, separate from the app bundle (it is meant to be served on its own, for example from Cloudflare Pages, which is not set up).

- `index.template.html` and `styles.css`: the page. Light or dark follows the device; phone and desktop layouts. No scripts, no third-party fonts or analytics, no tenant data.
- `site.config.json`: the one place for sign-up and sign-in addresses and every placeholder (support contact, legal entity, privacy and terms links, hosting wording). A value starting with `TODO` shows on the page as a visible TODO marker.
- `build.mjs`: `node landing/build.mjs --check` writes `landing/dist/` (ignored by git) and fails if the output has a script, a third-party URL or an unfilled placeholder. The two fonts are copied from `web/node_modules` (run `npm ci` in `web/` first).

Sign up and Sign in go to `/signup` and `/signin` on the same host. If the page is hosted apart from the app, set the full app address in `site.config.json`.

Locally, `http://localhost:5173/` shows this page: the Vite dev and preview servers (`web/vite.config.ts`) and the demo's nginx (`demo/nginx.conf`) serve the built page at `/` for a visitor with no session, and the app for someone signed in (a plain `kartaa_in` cookie the app sets, `web/src/auth/session.ts`). This is for trying the product by hand; hosting the page for real is a separate step.

## Production routing (kartaa.com)

One CloudFront distribution serves both the landing page and the app from the same private web bucket in Mumbai (static files only; no new service, no new data location). `infra/modules/cdn/viewer_request.js` decides the file for each path before the cache lookup:

| Path | File |
| --- | --- |
| `/`, visitor (no `kartaa_in=1` cookie) | `_landing/index.html` (this site) |
| `/`, signed in (`kartaa_in=1`) | `index.html` (the app, which sends the person to their home) |
| `/styles.css`, `/fonts/*` | `_landing/styles.css`, `_landing/fonts/*` |
| `/signin`, `/signup`, `/b/...` and other routes | `index.html` (the app) |
| `/assets/*`, `/favicon.svg` | the app's own files |

The Sign in and Sign up buttons on the page link to `/signin` and `/signup`. The deploy workflow builds this site (`node landing/build.mjs --check`) and syncs it to `_landing/` in the bucket with `no-cache`, so a person who just signed in and types the address again gets the app, not a cached landing page. The `kartaa_in` cookie holds no identity or token and grants nothing; it only picks which static page is returned (the app checks the real session itself). The production Content-Security-Policy (`default-src 'self'`) blocks inline styles and scripts, so `--check` rejects them. `node infra/modules/cdn/routing.test.mjs` runs the routing function on sample requests. Not yet tried on a real distribution: nothing is deployed.
