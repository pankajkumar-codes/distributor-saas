"""Products and their rate history (LLD-3 §2, §3, §6.1), in the caller's unit of work.

Every statement runs as app_rw under the business's row-level security, so a product
of another business simply isn't there (404). Writes lock the product row first: that
serialises rate adds (AC3-3), voids, edits, deletes and sales' mark_used (§8.1).
"""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.modules.refdata import value_on
from platform_common import audit
from platform_common.errors import Conflict, Deny, Invalid
from platform_common.ids import uuid7
from platform_common.permissions import require_reason
from platform_common.uow import UnitOfWork

from . import checks
from .rates import RateRow, check_rate, live, parse_rate, rate_on

CONFIRMERS = ("owner", "admin")  # L3-3: a rule inside catalog.edit
EDITABLE = ("code", "name", "hsn", "uqc", "sale_rate", "barcode", "tax_category", "has_cess")

_FIELDS = ("id", "code", "name", "hsn", "uqc", "sale_rate", "barcode", "tax_category", "has_cess", "status",
           "version")
_COLUMNS = ", ".join(_FIELDS) + ", first_used_at is not null as in_use"


@dataclass(frozen=True)
class Product:
    id: uuid.UUID
    code: str
    name: str
    hsn: str | None
    uqc: str
    sale_rate: Decimal
    barcode: str | None
    tax_category: str
    has_cess: bool
    status: str
    version: int
    in_use: bool


def _product(row) -> Product:
    return Product(*row[: len(_FIELDS) + 1])  # the fields, then in_use


def _business(uow: UnitOfWork) -> uuid.UUID:
    return uow.principal.business_id


def _me(uow: UnitOfWork) -> uuid.UUID:
    return uow.principal.user_id


def _get(uow: UnitOfWork, product_id: uuid.UUID, *, lock: bool = False) -> Product:
    row = uow.tx.execute(
        text(f"select {_COLUMNS} from catalog.products where id = :p and status <> 'deleted'"
             + (" for update" if lock else "")),
        {"p": product_id},
    ).one_or_none()
    if row is None:
        raise Deny("not_found")  # unknown, another business's, or deleted (§2.1)
    return _product(row)


def rate_rows(uow: UnitOfWork, product_id: uuid.UUID) -> list[RateRow]:
    return [
        RateRow(*r)
        for r in uow.tx.execute(
            text(
                "select r.id, r.rate, r.valid_from,"
                " exists (select 1 from catalog.product_rate_voids v where v.rate_id = r.id),"
                " coalesce((select c.action = 'confirm' from catalog.product_rate_confirmations c"
                "           where c.rate_id = r.id order by c.created_at desc, c.id desc limit 1), false)"
                " from catalog.product_rates r where r.product_id = :p order by r.valid_from, r.created_at"
            ),
            {"p": product_id},
        )
    ]


def warnings(p: Product, rate_confirmed: bool | None) -> list[dict]:
    """Shown on M8; none blocks a save (§4). `rate_confirmed` is None when no rate is in force."""
    out = []
    if p.hsn is None:
        out.append({"code": "hsn_missing", "field": "hsn", "message": "Missing HSN: add it before invoicing"})
    if p.tax_category == "taxable" and rate_confirmed is False:
        out.append({"code": "rate_unconfirmed", "field": "rate",
                    "message": "GST rate not confirmed with your CA"})
    if p.uqc == "OTH":
        out.append({"code": "uqc_other", "field": "uqc", "message": "Others: your CA may prefer a specific unit"})
    if p.has_cess:
        out.append({"code": "cess_not_supported", "field": "has_cess",
                    "message": "Products with cess can't go on an invoice yet"})
    if p.tax_category != "taxable":
        out.append({"code": "not_taxable", "field": "tax_category",
                    "message": "Only taxable products can go on a tax invoice for now"})
    return out


# --- Reads -------------------------------------------------------------------------


def get(uow: UnitOfWork, product_id: uuid.UUID) -> tuple[Product, list[RateRow], dict]:
    p = _get(uow, product_id)
    return p, rate_rows(uow, product_id), confirmations(uow, product_id)


def confirmations(uow: UnitOfWork, product_id: uuid.UUID) -> dict:
    """rate_id -> the latest confirmation event (state, by, at, note)."""
    out = {}
    for rate_id, action, by, at, note in uow.tx.execute(
        text(
            "select distinct on (c.rate_id) c.rate_id, c.action, c.created_by, c.created_at, c.note"
            " from catalog.product_rate_confirmations c join catalog.product_rates r on r.id = c.rate_id"
            " where r.product_id = :p order by c.rate_id, c.created_at desc, c.id desc"
        ),
        {"p": product_id},
    ):
        out[rate_id] = {"state": "confirmed" if action == "confirm" else "unconfirmed", "by": by, "at": at,
                        "note": note}
    return out


def search(uow: UnitOfWork, *, q: str | None, status: str, filter_: str | None, on: date, limit: int,
           offset: int) -> tuple[list[tuple[Product, dict | None]], bool]:
    """Name fragment, code prefix or exact barcode (L3-10), the business's rows only."""
    where = ["p.status <> 'deleted'"]
    params: dict = {"on": on, "limit": limit + 1, "offset": offset}
    if status in ("active", "archived"):
        where.append("p.status = :status")
        params["status"] = status
    if q and q.strip():
        needle = q.strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        where.append("(lower(p.name) like :frag or lower(p.code) like :prefix or lower(p.barcode) = :exact)")
        params.update(frag=f"%{needle}%", prefix=f"{needle}%", exact=q.strip().lower())
    if filter_ == "no_hsn":
        where.append("p.hsn is null")
    elif filter_ == "rate_unconfirmed":
        where.append("p.tax_category = 'taxable' and not coalesce(cr.confirmed, false)")
    rows = uow.tx.execute(
        text(
            f"select {', '.join('p.' + c for c in _FIELDS)},"
            " p.first_used_at is not null, cr.rate as cr_rate, cr.rate_id as cr_rate_id,"
            " cr.valid_from as cr_valid_from, cr.confirmed as cr_confirmed"
            " from catalog.products p left join catalog.current_rates(:on) cr on cr.product_id = p.id"
            f" where {' and '.join(where)} order by lower(p.code), p.id limit :limit offset :offset"
        ),
        params,
    ).all()
    more = len(rows) > limit
    items = []
    for r in rows[:limit]:
        rate = None if r.cr_rate_id is None else {
            "rate": r.cr_rate, "rate_id": r.cr_rate_id, "valid_from": r.cr_valid_from, "confirmed": r.cr_confirmed,
        }
        items.append((_product(r), rate))
    return items, more


# --- Writes ------------------------------------------------------------------------


def _unique_violation(exc: IntegrityError) -> Invalid | None:
    constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
    if constraint == "products_code_uq":
        return Invalid("code_taken", "Another product already uses this code", field="code")
    if constraint == "products_barcode_uq":
        return Invalid("barcode_taken", "Another active product already uses this barcode", field="barcode")
    return None


def _write(uow: UnitOfWork, sql: str, params: dict):
    """Run a write in a savepoint, turning the two unique indexes into 422s."""
    try:
        with uow.tx.begin_nested():
            return uow.tx.execute(text(sql), params)
    except IntegrityError as exc:
        mapped = _unique_violation(exc)
        if mapped is None:
            raise
        raise mapped from None


def _check_fields(uow: UnitOfWork, fields: dict, today: date) -> dict:
    tx = uow.tx
    out = {}
    for key, value in fields.items():
        if key == "code":
            out[key] = checks.code(tx, value, today)
        elif key == "name":
            out[key] = checks.name(value)
        elif key == "hsn":
            out[key] = checks.hsn(tx, value, today)
        elif key == "uqc":
            out[key] = checks.uqc(tx, value, today)
        elif key == "sale_rate":
            out[key] = checks.sale_rate(value)
        elif key == "barcode":
            out[key] = checks.barcode(value)
        elif key == "tax_category":
            out[key] = checks.tax_category(value)
        elif key == "has_cess":
            out[key] = bool(value)
    return out


def _insert_rate(uow: UnitOfWork, product_id: uuid.UUID, rate: Decimal, valid_from: date) -> uuid.UUID:
    rate_id = uuid7()
    uow.tx.execute(
        text(
            "insert into catalog.product_rates (id, business_id, product_id, rate, valid_from, source, created_by)"
            " values (:id, :b, :p, :r, :f, 'manual', :me)"
        ),
        {"id": rate_id, "b": _business(uow), "p": product_id, "r": rate, "f": valid_from, "me": _me(uow)},
    )
    return rate_id


def create(uow: UnitOfWork, body: dict, today: date) -> uuid.UUID:
    fields = _check_fields(uow, {k: body.get(k) for k in EDITABLE}, today)
    rate = body.get("rate")
    if fields["tax_category"] == "taxable":
        # One rule, with or without cess [RM43-8]; the app never fills a rate (AC3-4).
        if rate is None:
            raise Invalid("rate_required", "A taxable product needs its GST rate and the date it applies from",
                          field="rate")
        value = parse_rate(rate["rate"])
        check_rate(uow.tx, value, rate["valid_from"], today)
    elif rate is not None:
        raise Invalid("rate_not_allowed", "Exempt, nil-rated and non-GST products have no GST rate", field="rate")
    product_id = uuid7()
    _write(
        uow,
        "insert into catalog.products (id, business_id, code, name, hsn, uqc, sale_rate, barcode, tax_category,"
        " has_cess, created_by, updated_by) values (:id, :b, :code, :name, :hsn, :uqc, :sale_rate, :barcode,"
        " :tax_category, :has_cess, :me, :me)",
        {"id": product_id, "b": _business(uow), "me": _me(uow), **fields},
    )
    audit.record(uow, "product.created", "product", product_id, data={"code": fields["code"]})
    if rate is not None:
        rate_id = _insert_rate(uow, product_id, value, rate["valid_from"])
        audit.record(uow, "product.rate_added", "product", product_id,
                     data={"rate_id": str(rate_id), "rate": f"{value.normalize():f}",
                           "valid_from": rate["valid_from"].isoformat()})
    return product_id


def _check_version(p: Product, if_match: int | None) -> None:
    if if_match is None:
        raise Invalid("if_match_required", "Send the version you edited as If-Match", field="If-Match")
    if p.version != if_match:
        raise Conflict("stale_record", "Someone changed this product since you opened it",
                       fix="Reload it and make your change again")


def update(uow: UnitOfWork, product_id: uuid.UUID, changes: dict, if_match: int | None, today: date) -> None:
    p = _get(uow, product_id, lock=True)
    _check_version(p, if_match)
    fields = _check_fields(uow, {k: v for k, v in changes.items() if k in EDITABLE}, today)
    if "tax_category" in fields and (fields["tax_category"] == "taxable") != (p.tax_category == "taxable"):
        # A taxable product's rate rows would be left meaningless, or a new taxable one
        # would have none; neither is guessed. The fix is a new product (or delete if unused).
        raise Invalid("tax_category_locked", "A product can't move between taxable and not taxable",
                      field="tax_category", fix="Create a new product with the right category")
    changed = {k: v for k, v in fields.items() if getattr(p, k) != v}
    if not changed:
        return
    sets = ", ".join(f"{k} = :{k}" for k in changed)
    _write(
        uow,
        f"update catalog.products set {sets}, version = version + 1, updated_at = now(), updated_by = :me"
        " where id = :p",
        {**changed, "me": _me(uow), "p": product_id},
    )
    audit.record(uow, "product.updated", "product", product_id,
                 data={"code": changed.get("code", p.code), "fields": sorted(changed)})


def set_archived(uow: UnitOfWork, product_id: uuid.UUID, archived: bool) -> None:
    """No If-Match [RM43-7]: idempotent, changes only status, and bumps version."""
    p = _get(uow, product_id, lock=True)
    target = "archived" if archived else "active"
    if p.status == target:
        return
    _write(
        uow,
        "update catalog.products set status = :s, version = version + 1, updated_at = now(), updated_by = :me"
        " where id = :p",
        {"s": target, "me": _me(uow), "p": product_id},
    )
    audit.record(uow, "product.archived" if archived else "product.unarchived", "product", product_id,
                 data={"code": p.code})


def delete(uow: UnitOfWork, product_id: uuid.UUID, if_match: int | None) -> None:
    """A soft delete while never used [RM43-1, RM43-4]: one statement, so finalize's
    mark_used and this serialise on the row lock."""
    if if_match is None:
        raise Invalid("if_match_required", "Send the version you saw as If-Match", field="If-Match")
    done = uow.tx.execute(
        text(
            "update catalog.products set status = 'deleted', version = version + 1, updated_at = now(),"
            " updated_by = :me where id = :p and version = :v and first_used_at is null and status <> 'deleted'"
            " returning code"
        ),
        {"me": _me(uow), "p": product_id, "v": if_match},
    ).one_or_none()
    if done is None:
        p = _get(uow, product_id)  # 404 if gone
        if p.in_use:
            raise Conflict("product_in_use", "This product is on invoices, so it can be archived but not deleted",
                           fix="Archive it instead")
        _check_version(p, if_match)
        raise RuntimeError("delete matched no row for an unused, current product")
    audit.record(uow, "product.deleted", "product", product_id, data={"code": done.code})


def add_rate(uow: UnitOfWork, product_id: uuid.UUID, raw_rate: str, valid_from: date, today: date) -> uuid.UUID:
    p = _get(uow, product_id, lock=True)
    if p.tax_category != "taxable":
        raise Invalid("rate_not_allowed", "Exempt, nil-rated and non-GST products have no GST rate", field="rate")
    value = parse_rate(raw_rate)
    check_rate(uow.tx, value, valid_from, today)
    # Live valid_from are unique per product; the voids table hides from a unique index,
    # so the rule is checked here, under the product's lock (§3, AC3-3).
    if any(r.valid_from == valid_from for r in live(rate_rows(uow, product_id))):
        raise Conflict("rate_exists_on_date", f"This product already has a rate from {valid_from:%d-%m-%Y}",
                       fix="Void that rate first if it was wrong")
    rate_id = _insert_rate(uow, product_id, value, valid_from)
    uow.tx.execute(text("update catalog.products set version = version + 1 where id = :p"), {"p": product_id})
    audit.record(uow, "product.rate_added", "product", product_id,
                 data={"rate_id": str(rate_id), "rate": f"{value.normalize():f}", "valid_from": valid_from.isoformat()})
    return rate_id


def _rate(uow: UnitOfWork, product_id: uuid.UUID, rate_id: uuid.UUID) -> RateRow:
    for r in rate_rows(uow, product_id):
        if r.id == rate_id:
            return r
    raise Deny("not_found")


def void_rate(uow: UnitOfWork, product_id: uuid.UUID, rate_id: uuid.UUID, reason: str | None) -> None:
    _get(uow, product_id, lock=True)
    reason = require_reason("product.rate_voided", reason)
    rows = rate_rows(uow, product_id)
    target = _rate(uow, product_id, rate_id)
    if target.voided:
        raise Conflict("rate_already_voided", "This rate is already voided")
    if len(live(rows)) == 1:
        raise Conflict("last_rate", "A taxable product needs at least one rate",
                       fix="Add the correct rate first, then void this one")
    uow.tx.execute(
        text("insert into catalog.product_rate_voids (rate_id, business_id, reason, created_by)"
             " values (:r, :b, :reason, :me)"),
        {"r": rate_id, "b": _business(uow), "reason": reason, "me": _me(uow)},
    )
    uow.tx.execute(text("update catalog.products set version = version + 1 where id = :p"), {"p": product_id})
    audit.record(uow, "product.rate_voided", "product", product_id, reason=reason,
                 data={"rate_id": str(rate_id), "rate": f"{target.rate.normalize():f}",
                       "valid_from": target.valid_from.isoformat()})


def set_confirmed(uow: UnitOfWork, product_id: uuid.UUID, rate_id: uuid.UUID, confirmed: bool,
                  note: str | None) -> None:
    """L3-2, L3-3: an insert-only event; only owner and admin. Confirm and unconfirm don't
    bump version (§3): they change nothing an edit or import could overwrite."""
    if uow.principal.role not in CONFIRMERS:
        raise Deny("role_denied")
    _get(uow, product_id, lock=True)
    target = _rate(uow, product_id, rate_id)
    if target.voided:
        raise Conflict("rate_voided", "A voided rate can't be confirmed or unconfirmed")
    action = "product.rate_confirmed" if confirmed else "product.rate_unconfirmed"
    if confirmed:
        note = (note or "").strip() or None
        if note is not None and len(note) > 500:
            raise Invalid("note_too_long", "A note is at most 500 characters", field="note")
    else:
        note = require_reason(action, note)
    uow.tx.execute(
        text("insert into catalog.product_rate_confirmations (id, business_id, rate_id, action, note, created_by)"
             " values (:id, :b, :r, :a, :n, :me)"),
        {"id": uuid7(), "b": _business(uow), "r": rate_id, "a": "confirm" if confirmed else "unconfirm",
         "n": note, "me": _me(uow)},
    )
    audit.record(uow, action, "product", product_id, reason=None if confirmed else note,
                 data={"rate_id": str(rate_id), "rate": f"{target.rate.normalize():f}"})


def current(uow: UnitOfWork, product_id: uuid.UUID, on: date):
    """The rate on `on` with its warning flag, or None (AC3-1)."""
    days = int(value_on(uow.tx, "catalog.rate_change_warning_days", on))
    return rate_on(rate_rows(uow, product_id), on, days)

