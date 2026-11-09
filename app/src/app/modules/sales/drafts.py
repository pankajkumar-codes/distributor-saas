"""Invoice drafts (LLD-4 §2.1, §9), in the caller's unit of work.

A draft is mutable while open and is not a GST record: it is saved whole (PUT) under
If-Match, and an open draft can be hard-deleted (audited). Nothing here computes tax or
allocates a number; that is later slices. Money and quantities are decimal strings and
only strings (AC4-15). Customers and products are read through catalog.interface, and the
bill-to / ship-to copy is taken at every save (§8.1). Columns the table has but no route writes yet (bill_to / ship_to overrides,
ship_to_third_party, pos_override and its reason, the credit-note fields) wait for the
computation and credit-note slices. Only invoice drafts for now; credit
note drafts come with the credit-note slice.
"""

import re
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import bindparam, text
from sqlalchemy.types import JSON

from app.modules.business.interface import check_state
from app.modules.catalog.interface import customer_snapshot, products_for_lines
from platform_common import audit
from platform_common.money import to_decimal
from platform_common.errors import Conflict, Deny, Invalid
from platform_common.ids import uuid7
from platform_common.uow import UnitOfWork

from .compute import Computation, DraftIn, DraftLineIn, compute, load_inputs

MAX_LINES = 200
MAX_CHARGES = 20
_MONEY = re.compile(r"^[0-9]{1,16}(\.[0-9]{1,2})?$")
_QTY = re.compile(r"^[0-9]{1,15}(\.[0-9]{1,3})?$")
_TWO, _THREE = Decimal("0.01"), Decimal("0.001")
_HUNDRED = Decimal(100)
_COLUMNS = ("id, kind, status, version, customer_id, cash_buyer, bill_to, ship_to, ship_to_third_party, doc_date,"
            " invoice_discount, charges, eway, customer_collects, pos_override, pos_override_reason, created_at, updated_at")


def _business(uow: UnitOfWork) -> uuid.UUID:
    return uow.principal.business_id


def money(raw, field: str) -> Decimal:
    """A decimal string with up to 2 places; a JSON number, a negative or a float is refused."""
    if not isinstance(raw, str) or not _MONEY.match(raw.strip()):
        raise Invalid("amount_invalid", "Enter the amount as a number with up to 2 decimals, like 120.50", field=field)
    return Decimal(raw.strip()).quantize(_TWO)


def quantity(raw, field: str) -> Decimal:
    if not isinstance(raw, str) or not _QTY.match(raw.strip()) or Decimal(raw.strip()) <= 0:
        raise Invalid("quantity_invalid", "Enter a quantity above 0 with up to 3 decimals", field=field)
    return Decimal(raw.strip()).quantize(_THREE)


def _party(c) -> dict:
    return {"name": c.name, "gstin": c.gstin, "line1": c.billing.line1, "line2": c.billing.line2,
            "city": c.billing.city, "pin": c.billing.pin, "state_code": c.billing.state_code}


def _ship(c) -> dict:
    d = c.delivery
    return {"line1": d.line1, "line2": d.line2, "city": d.city, "pin": d.pin, "state_code": d.state_code}


def _checked(uow: UnitOfWork, body: dict, today: date) -> tuple[dict, list[dict]]:
    """The whole draft as it will be saved, or Invalid."""
    tx = uow.tx
    cols: dict = {"customer_id": None, "cash_buyer": None, "bill_to": None, "ship_to": None}
    if body.get("customer_id") is not None and body.get("cash_buyer") is not None:
        raise Invalid("buyer_ambiguous", "Choose a customer or a cash sale, not both", field="cash_buyer")
    if body.get("customer_id") is not None:
        try:
            c = customer_snapshot(tx, uuid.UUID(str(body["customer_id"])))
        except (Deny, ValueError):
            raise Invalid("customer_not_found", "Choose a customer from your list", field="customer_id") from None
        if c.status != "active":
            raise Invalid("customer_archived", "This customer is archived; restore it to bill them", field="customer_id")
        cols.update(customer_id=c.customer_id, bill_to=_party(c), ship_to=_ship(c))
    elif body.get("cash_buyer") is not None:
        buyer = body["cash_buyer"]
        check_state(tx, buyer.get("state_code") or "", today, "cash_buyer.state_code")
        cols["cash_buyer"] = {k: (buyer.get(k) or "").strip() or None for k in ("name", "state_code", "address")}
        cols["bill_to"] = {"name": cols["cash_buyer"]["name"], "state_code": buyer["state_code"]}
    cols["doc_date"] = body.get("doc_date")
    cols["invoice_discount"] = money(body.get("invoice_discount", "0"), "invoice_discount")
    if len(body.get("charges") or []) > MAX_CHARGES:
        raise Invalid("too_many_charges", f"An invoice can have at most {MAX_CHARGES} charges", field="charges")
    cols["charges"] = [
        {"label": (ch.get("label") or "").strip(), "amount": str(money(ch.get("amount"), f"charges.{i}.amount"))}
        for i, ch in enumerate(body.get("charges") or [])
    ]
    for i, ch in enumerate(cols["charges"]):
        if not ch["label"]:
            raise Invalid("charge_label_required", "Name the charge", field=f"charges.{i}.label")
    cols["eway"] = body.get("eway")
    cols["customer_collects"] = bool(body.get("customer_collects", False))
    lines = body.get("lines") or []
    if len(lines) > MAX_LINES:
        raise Invalid("too_many_lines", f"An invoice can have at most {MAX_LINES} lines", field="lines")
    ids = []
    for i, ln in enumerate(lines):
        try:
            ids.append(uuid.UUID(str(ln.get("product_id"))))
        except ValueError:
            raise Invalid("product_not_found", "Choose a product from your list", field=f"lines.{i}.product_id") from None
    found = products_for_lines(tx, ids, today)
    out = []
    for i, (ln, pid) in enumerate(zip(lines, ids, strict=True), start=1):
        field = f"lines.{i - 1}"
        p = found.get(pid)
        if p is None:
            raise Invalid("product_not_found", "Choose a product from your list", field=f"{field}.product_id")
        if p.status != "active":
            raise Invalid("product_archived", "This product is archived; restore it to sell it", field=f"{field}.product_id")
        kind, value = ln.get("discount_kind"), ln.get("discount_value")
        if (kind is None) != (value is None) or kind not in (None, "amount", "percent"):
            raise Invalid("discount_invalid", "Give a discount as an amount or a percent, with its value", field=f"{field}.discount_kind")
        disc = money(value, f"{field}.discount_value") if value is not None else None
        if kind == "percent" and disc > _HUNDRED:
            raise Invalid("discount_invalid", "A percent discount can't be more than 100", field=f"{field}.discount_value")
        price = money(ln["unit_price"], f"{field}.unit_price") if ln.get("unit_price") is not None else p.sale_rate
        out.append({"id": uuid7(), "line_no": i, "product_id": pid, "quantity": quantity(ln.get("quantity"), f"{field}.quantity"),
                    "unit_price": price, "discount_kind": kind, "discount_value": disc})
    return cols, out


def _lines(uow: UnitOfWork, draft_id: uuid.UUID) -> list[dict]:
    rows = uow.tx.execute(
        text("select id, line_no, product_id, quantity, unit_price, discount_kind, discount_value"
             " from sales.draft_lines where draft_id = :d and business_id = :b order by line_no"),
        {"d": draft_id, "b": _business(uow)},
    ).mappings()
    return [dict(r) for r in rows]


def get(uow: UnitOfWork, draft_id: uuid.UUID, *, lock: bool = False) -> dict:
    row = uow.tx.execute(
        text(f"select {_COLUMNS} from sales.drafts where id = :d and business_id = :b and status = 'open'"
             + (" for update" if lock else "")),
        {"d": draft_id, "b": _business(uow)},
    ).mappings().one_or_none()
    if row is None:
        raise Deny("not_found")
    return {**row, "lines": _lines(uow, draft_id)}


def search(uow: UnitOfWork, *, kind: str | None, q: str | None, limit: int, offset: int) -> tuple[list[dict], bool]:
    where, params = ["business_id = :b", "status = 'open'"], {"b": _business(uow), "limit": limit + 1, "offset": offset}
    if kind:
        where.append("kind = :kind")
        params["kind"] = kind
    if q and q.strip():
        needle = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        where.append("bill_to ->> 'name' ilike :frag")
        params["frag"] = f"%{needle}%"
    rows = uow.tx.execute(
        text(f"select {_COLUMNS} from sales.drafts where {' and '.join(where)}"
             " order by updated_at desc, id limit :limit offset :offset"), params).mappings().all()
    return [{**r, "lines": []} for r in rows[:limit]], len(rows) > limit


def _write_lines(uow: UnitOfWork, draft_id: uuid.UUID, lines: list[dict]) -> None:
    uow.tx.execute(text("delete from sales.draft_lines where draft_id = :d and business_id = :b"),
                   {"d": draft_id, "b": _business(uow)})
    for ln in lines:
        uow.tx.execute(
            text("insert into sales.draft_lines (id, business_id, draft_id, line_no, product_id, quantity, unit_price,"
                 " discount_kind, discount_value) values (:id, :b, :d, :line_no, :product_id, :quantity, :unit_price,"
                 " :discount_kind, :discount_value)"),
            {**ln, "b": _business(uow), "d": draft_id})


_JSON = ("cash_buyer", "bill_to", "ship_to", "charges", "eway")


def _bind(sql: str):
    return text(sql).bindparams(*[bindparam(k, type_=JSON(none_as_null=True)) for k in _JSON])


def create(uow: UnitOfWork, body: dict, today: date) -> uuid.UUID:
    if body.get("kind", "invoice") != "invoice":
        raise Invalid("kind_unsupported", "Only invoices can be drafted for now", field="kind")
    cols, lines = _checked(uow, body, today)
    draft_id, me = uuid7(), uow.principal.user_id
    uow.tx.execute(
        _bind("insert into sales.drafts (id, business_id, kind, customer_id, cash_buyer, bill_to, ship_to, doc_date,"
              " invoice_discount, charges, eway, customer_collects, created_by, updated_by) values (:id, :b, 'invoice', :customer_id,"
              " :cash_buyer, :bill_to, :ship_to, :doc_date, :invoice_discount, :charges, :eway, :customer_collects, :me, :me)"),
        {"id": draft_id, "b": _business(uow), "me": me, **cols})
    _write_lines(uow, draft_id, lines)
    audit.record(uow, "draft.created", "draft", draft_id, data={})
    return draft_id


def replace(uow: UnitOfWork, draft_id: uuid.UUID, body: dict, if_match: int | None, today: date) -> None:
    if body.get("kind", "invoice") != "invoice":
        raise Invalid("kind_unsupported", "Only invoices can be drafted for now", field="kind")
    d = get(uow, draft_id, lock=True)
    _check_version(d, if_match)
    cols, lines = _checked(uow, body, today)
    uow.tx.execute(
        _bind("update sales.drafts set customer_id = :customer_id, cash_buyer = :cash_buyer, bill_to = :bill_to,"
              " ship_to = :ship_to, doc_date = :doc_date, invoice_discount = :invoice_discount, charges = :charges,"
              " eway = :eway, customer_collects = :customer_collects, version = version + 1, updated_at = now(), updated_by = :me"
              " where id = :id and business_id = :b and status = 'open'"),
        {"id": draft_id, "b": _business(uow), "me": uow.principal.user_id, **cols})
    _write_lines(uow, draft_id, lines)
    audit.record(uow, "draft.updated", "draft", draft_id, data={})


def _check_version(d: dict, if_match: int | None) -> None:
    if if_match is None:
        raise Invalid("if_match_required", "Send the version you edited as If-Match", field="If-Match")
    if d["version"] != if_match:
        raise Conflict("stale_record", "Someone changed this draft since you opened it",
                       fix="Reload it and make your change again")


def delete(uow: UnitOfWork, draft_id: uuid.UUID, if_match: int | None) -> None:
    d = get(uow, draft_id, lock=True)
    _check_version(d, if_match)
    uow.tx.execute(text("delete from sales.drafts where id = :d and business_id = :b and status = 'open'"),
                   {"d": draft_id, "b": _business(uow)})
    audit.record(uow, "draft.deleted", "draft", draft_id, data={})


def computation(uow: UnitOfWork, d: dict, *, today: date) -> Computation:
    """The draft's tax computation (LLD-4 §3): `compute(load_inputs(...))` over the stored
    draft `d` (as `get` returns it). Raises Invalid when the amounts can't be computed (a
    discount above the base, and so on), and Invalid("customer_not_found") for a customer
    deleted since the draft was saved. A draft that is merely incomplete comes back with
    `blocks`, never an error. Callers save first and compute second inside the same unit of
    work, so an Invalid from here does block the save: the whole request
    rolls back. `today` is the IST date; a draft without a date uses it."""
    draft = DraftIn(
        doc_date=d["doc_date"] or today,
        customer_id=d["customer_id"],
        cash_buyer=d["cash_buyer"],
        bill_to=d["bill_to"],
        ship_to=d["ship_to"],
        ship_to_third_party=d["ship_to_third_party"],
        customer_collects=d["customer_collects"],
        invoice_discount=d["invoice_discount"],
        charges=tuple((c["label"], to_decimal(c["amount"])) for c in d["charges"]),
        pos_override=d["pos_override"],
        pos_override_reason=d["pos_override_reason"],
        has_eway_details=any((d["eway"] or {}).values()),
    )
    lines = [
        DraftLineIn(ln["line_no"], ln["product_id"], ln["quantity"], ln["unit_price"], ln["discount_kind"],
                    ln["discount_value"])
        for ln in d["lines"]
    ]
    try:
        return compute(load_inputs(uow.tx, draft, lines, today=today))
    except Deny as denied:
        if denied.reason != "not_found" or draft.customer_id is None:
            raise  # only the buyer lookup's miss means a deleted customer
        raise Invalid("customer_not_found", "This draft's customer was deleted; choose a customer",
                      field="customer_id") from None
