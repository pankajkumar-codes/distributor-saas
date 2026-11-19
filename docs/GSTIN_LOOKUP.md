# GSTIN lookup at sign-up (#249, D-100)

Typing a well-formed GSTIN on sign-up step 3 fills the legal name, trade name and address from a lookup. It is a convenience:
the person checks the details and can change or ignore all of them. It is not a check by us that the GSTIN is registered or
active, and nothing on screen says "verified" (we test only the format and check digit).

## What is built

- `POST /api/v1/gstin-lookup` `{ "gstin": "..." }`, signed in, no business needed. The GSTIN is in the body so it stays out of access logs.
  - 200 `found: true` with `legal_name`, `trade_name`, `status` (the provider's word), `address`, `source`.
  - 200 `found: false` when the provider has no such GSTIN (not an error: our check only proved the format).
  - 422 `gstin_length`, `gstin_shape` or `gstin_check_char` before any provider is asked.
  - 429 `rate_limited` with `Retry-After`: `business.gstin_lookup.per_user_per_hour` (30, provisional), counted per signed-in user.
  - 503 `lookup_off` (no provider configured) or `lookup_unavailable` (the provider did not answer).
- The provider sits behind `LookupProvider` in `app/src/app/modules/business/gstin_lookup.py`. The deployment setting `GSTIN_LOOKUP_PROVIDER` picks it:
  unset or `off` (the default everywhere real), `fake` (local and test only), or a vendor name once its adapter exists.
- The web form looks up each well-formed GSTIN once and fills only fields that are empty or still hold what an earlier lookup filled.
  Anything the person typed is kept. A lookup that is off says nothing; one that fails, is limited or finds nothing says so in one plain
  line and the form carries on.
- Nothing from the lookup is stored. Results are not cached yet.

## Data sent to the provider (D-094)

Only the 15-character GSTIN, from our server (never the browser), over HTTPS. No user, business, invoice or filing data. A GSTIN is
shown to anyone by the GST portal's public search, but D-094 keeps GST data in India, so before switching on we need the vendor's
written statement that requests are handled on India-hosted infrastructure and their data-processing terms. The research could not
confirm either for any vendor (`research/gstin-lookup-providers-2026-11-16.md`).

## The fake provider (local demo and tests)

Invents the same details every time for the same GSTIN; the 13th character picks the case:
`9` not found, `8` cancelled registration, `7` provider down, anything else an active taxpayer. The local demo (`./demo.sh`) runs it,
so a made-up valid GSTIN fills "Demo Traders ..." on sign-up. It refuses to start outside local and test environments.

## What only Pankaj can do to switch on a real provider

1. Ask Masters India (first choice, a GSTN-appointed GSP) for a sandbox account for its GSTIN verification API. If they are slow or
   too dear, GSTZen or GSTVerify are the low-volume fallbacks. This is the paid-service approval CLAUDE.md asks for: do not sign a
   contract without checking the price (the research found Rs 0.10 to Rs 5 a call, unverified).
2. Ask them for: (a) a sample JSON response for one active and one cancelled GSTIN, (b) a written statement that the request is served
   from India, (c) their rate limits and data-processing terms.
3. Put the API key in Parameter Store and send the sample JSON to the team. The adapter is one small file implementing `LookupProvider`
   (map their fields to `Taxpayer`, turn timeouts and non-200 answers into `LookupUnavailable`), plus tests against the sample.
   We do not write it earlier because the response shape is the vendor's and we will not guess it.
4. Set `GSTIN_LOOKUP_PROVIDER` to the vendor's name in the Lambda environment (Terraform) to switch on. Unset it to switch off.

## Not decided or not verified

- Vendor, price and contract: Pankaj's call (CLAUDE.md approval gates).
- Whether the vendor's records carry address lines in a usable shape, and the registration date: unconfirmed until we see a sample.
- Caching per GSTIN to cut cost: add with the real adapter.
- Business-type and turnover are never filled by the lookup.
