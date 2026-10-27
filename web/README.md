# Web app (LLD-1 §11)

React + TypeScript (Vite), React Router and TanStack Query, per TD-2 and HLD §9. S1 so far:
`/signup` (step 1 email and password, step 2 the emailed code) and a placeholder
`/onboarding/business`.

## Running it

```
make db-up db-migrate run-api      # the API on :8000, codes go to build/mail/outbox.jsonl
cd web && npm ci && npm run dev    # http://localhost:5173, /api proxied to :8000
```

Use `localhost`, not `127.0.0.1`: the API accepts the sign-up verify call only from the
origin `http://localhost:5173` locally.

- `npm test`: Vitest unit tests (`tests/unit`).
- `npm run e2e`: Playwright (`tests/e2e`) against a built app on :5173 and the API on
  :8000; it reads codes from `../build/mail/outbox.jsonl` (`MAIL_OUTBOX` overrides).
- `npm run gen:api`: regenerates `src/api/schema.d.ts` from `app/openapi.json`.

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

## Rules

- **RM-4.1 row 13:** the sign-up flow keeps the email in `history.state`, never in a query
  string such as `?email=`, so it stays out of browser history and CloudFront access logs.
  `tests/unit/signup.test.tsx` and the Playwright test check it.
- Tokens live in memory only, never in `localStorage` or `sessionStorage` (LLD-1 §11.3).
  ESLint refuses either global under `src/`.
- `playwright-core` is overridden to 1.63.0 so `@axe-core/playwright` uses the same
  Playwright as `@playwright/test`, not a newer copy.
