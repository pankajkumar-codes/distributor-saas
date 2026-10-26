# Web app (LLD-1 §11)

React + TypeScript (Vite), React Router and TanStack Query, per TD-2 and HLD §9. The
screens come in S1; this folder holds the pinned dependencies and their CI checks only
(build-readiness 4.6).

## Dependencies

- Every version in `package.json` is exact (`.npmrc` has `save-exact=true`), and
  `package-lock.json` is committed. `node scripts/check-pins.mjs` fails on a `^`, `~` or
  range, and CI installs with `npm ci`, which refuses a lockfile that doesn't match.
- New versions are at least two weeks old when added, as a buffer against a
  compromised release.
- `@playwright/test` matches the Playwright already in the dev image (1.63.0), so it
  finds the installed Chromium.
- CI runs `npm audit --omit=dev --audit-level=high`: a high or critical advisory in a
  runtime dependency fails the `web` job (RM41-5).
- Install scripts are off in CI (`npm ci --ignore-scripts`). A dependency that needs one
  has to be named in its PR.

**Regenerating the lockfile:** npm 10 (bundled with Node 22) crashes while resolving this
tree's optional peers (`Cannot read properties of null (reading 'edgesOut')`), so
regenerate with npm 11:

```
npx npm@11.6.2 install --package-lock-only --ignore-scripts
```

`npm ci` with npm 10 installs from the lockfile without trouble.

## Rules carried into S1

- **RM-4.1 row 13:** the sign-up flow keeps the email in `history.state`, never in a query
  string such as `?email=`, so it stays out of browser history and CloudFront access logs.
  This is the S1 `/signup` screen's rule (LLD-1 §11.2); nothing here builds that screen yet.
- Tokens live in memory only, never in `localStorage` or `sessionStorage` (LLD-1 §11.3).
