# Catalog: products and GST rate history

LLD-3 part S3-a. The code is in `app/src/app/modules/catalog/`, and the migrations are catalog's `202610271010_catalog_products.sql` and `202610271020_catalog_trgm.sql`, plus refdata's `202610271000_refdata_uqc_codes.sql`. Customers (S3-b) and the product CSV import (S3-c) come next.

## Routes (all under `/api/v1/b/{id}`)

| Route | Permission | Notes |
|---|---|---|
| `GET /products` | `catalog.view` | `q` matches a name fragment, a code prefix or an exact barcode. `status` is `active` (default), `archived` or `all`. `filter` is `no_hsn` or `rate_unconfirmed`. `on` is the date for the rate shown, default today. Paging with `limit` and `offset`. |
| `POST /products` | `catalog.edit` | Needs an `Idempotency-Key`. A taxable product needs `rate: {rate, valid_from}`; other categories can't have one. |
| `GET /products/{pid}` | `catalog.view` | The product, with `version`, `in_use` and its whole rate history. |
| `PATCH /products/{pid}` | `catalog.edit` | Needs `If-Match: <version>`. A stale version gets 409 `stale_record`. |
| `POST /products/{pid}/archive`, `/unarchive` | `catalog.edit` | No `If-Match`. Idempotent, and bumps `version`. |
| `DELETE /products/{pid}` | `catalog.edit` | Needs `If-Match`. A soft delete, allowed only while the product has never been on an invoice (409 `product_in_use`). |
| `POST /products/{pid}/rates` | `catalog.edit` | `{rate, valid_from}`, with an `Idempotency-Key`. 409 `rate_exists_on_date`. |
| `POST /products/{pid}/rates/{rid}/void` | `catalog.edit` | A reason is required. 409 `last_rate`. |
| `POST /products/{pid}/rates/{rid}/confirm`, `/unconfirm` | `catalog.edit`, owner or admin only | Confirm takes an optional note; unconfirm needs a reason. |
| `GET /units` | `catalog.view` | The UQC list for the unit picker. |

## Rules

- **Rates come from refdata, never from the app.**
  - A rate must be on `gst.rate_values` for its `valid_from`.
  - `valid_from` must be on or after `gst.regime_start_date` and at most `catalog.rate_valid_from_max_days_ahead` days ahead.
  - Nothing fills or suggests a rate or an HSN (GC-P3).
  - The list only catches typos such as 81. Rates are compared as `Decimal`, so `"18.00"` is 18.
- **History is insert-only.**
  - `product_rates`, `product_rate_voids` and `product_rate_confirmations` take INSERT only.
  - A rate ends where the next live rate starts, and that end is computed, never stored.
  - A wrong rate is voided, with a reason, and a correct one is added.
  - The last live rate of a taxable product can't be voided.
- **Recent change.** A rate warns when it replaced an earlier one at most `catalog.rate_change_warning_days` (30, inclusive) days before the date it is read for.
- **Confirmed with CA** is the owner's or admin's own statement, recorded as an event with who and when. It never blocks anything.
- **HSN** is optional ("Missing HSN"). When given, it must match refdata `hsn.pattern` (4, 6 or 8 digits, provisional; the 8-digit cap is open in `OPEN_QUESTIONS.md`).
- **Unit** must be a code in `refdata.uqc_codes`. For each code, `code-official_description` equals the GSTR-1 template's UQC string; a test pins this against the template's master sheet.
- **Codes.** A product code is unique ignoring case among products that aren't deleted, archived ones included. A barcode is unique ignoring case among active products.
- **Tax category.** Only `taxable` products have rates. A product can't move between taxable and the other categories; to fix one, create a new product, or delete the old one if it was never used.
- **Money and rates** are decimal strings in and out. A JSON number is refused.
- **Tenant isolation.**
  - Every table has forced row-level security.
  - The rate tables use composite `(id, business_id)` foreign keys, so a row can't point at another business's product. Foreign key checks don't see row-level security, so the policies alone wouldn't stop that.

## For other modules (`catalog.interface`)

- `product_for_line(tx, product_id, on)` and `products_for_lines(tx, ids, on)`: the product, the rate in force on `on`, whether that rate is confirmed, and the recent-change flag. Sales uses these on invoice lines.
- `mark_used(tx, product_ids)`: called inside finalize. It sets `first_used_at` once and raises `product_deleted` if a product was deleted in the meantime.
- `setup_counts(tx, on)`: feeds Home's products tile.

## Not yet

- Customers (S3-b), and the CSV import (S3-c, which needs the job runner and the upload path).
- The HSN-digits-by-turnover warning (`hsn_min_digits`), which needs business refdata.
- Usage events (`setup.first_product`): there is no usage-event table yet.
- Lists use `limit` and `offset`, the platform's paging, rather than the cursor LLD-3 §6 mentions.
