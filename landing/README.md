# Kartaa landing page

A static page, separate from the app bundle (it is meant to be served on its own, for example from Cloudflare Pages, which is not set up).

- `index.template.html` and `styles.css`: the page. Light or dark follows the device; phone and desktop layouts. No scripts, no third-party fonts or analytics, no tenant data.
- `site.config.json`: the one place for sign-up and sign-in addresses and every placeholder (support contact, legal entity, privacy and terms links, hosting wording). A value starting with `TODO` shows on the page as a visible TODO marker.
- `build.mjs`: `node landing/build.mjs --check` writes `landing/dist/` (ignored by git) and fails if the output has a script, a third-party URL or an unfilled placeholder. The two fonts are copied from `web/node_modules` (run `npm ci` in `web/` first).

Sign up and Sign in go to `/signup` and `/signin` on the same host. If the page is hosted apart from the app, set the full app address in `site.config.json`.
