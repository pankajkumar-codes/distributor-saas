"""Customers (LLD-3 §2, §4, §6.2), in the caller's unit of work.

Every statement runs as app_rw under the business's row-level security, so another
business's customer simply isn't there (404). A write validates the whole customer as
it will be saved (a PATCH is merged onto the current row first), so the address rules
can't be dodged one field at a time. GSTIN checks are business's (gstin.md); they prove
the number is well formed, never that it is registered (GC-P6).
"""

import uuid
from dataclasses import dataclass, fields
from datetime import date

from sqlalchemy import text

from app.modules.business.interface import check_gstin, check_state, get_profile, gstin_message
from app.modules.refdata import value_on
from platform_common import audit
from platform_common.errors import Conflict, Deny, Invalid
from platform_common.ids import uuid7
from platform_common.uow import UnitOfWork

from . import checks

ADDRESS = ("line1", "line2", "city", "pin", "state_code")
_LIMITS = {"line1": 200, "line2": 200, "city": 100}  # the columns' widths


@dataclass(frozen=True)
class Customer:
    id: uuid.UUID
    name: str
    gstin: str | None
    gstin_state_code: str | None
    billing_line1: str | None
    billing_line2: str | None
    billing_city: str | None
    billing_pin: str | None
    billing_state_code: str
    delivery_same_as_billing: bool
    delivery_line1: str | None
    delivery_line2: str | None
    delivery_city: str | None
    delivery_pin: str | None
    delivery_state_code: str | None
    credit_days: int
    status: str
    version: int
    in_use: bool
    gstin_shared: bool  # another customer of this business has the same GSTIN

    def address(self, which: str) -> dict:
        return {k: getattr(self, f"{which}_{k}") for k in ADDRESS}


_COMPUTED = ("in_use", "gstin_shared")
_STORED = [f.name for f in fields(Customer) if f.name not in _COMPUTED]  # the columns
_SELECT = (
    ", ".join(f"c.{c}" for c in _STORED)
    + ", c.first_used_at is not null as in_use,"
    " c.gstin is not null and exists (select 1 from catalog.customers o where o.gstin = c.gstin"
    " and o.id <> c.id and o.status <> 'deleted') as gstin_shared"
)


def _business(uow: UnitOfWork) -> uuid.UUID:
    return uow.principal.business_id


def _me(uow: UnitOfWork) -> uuid.UUID:
    return uow.principal.user_id


def _get(uow: UnitOfWork, customer_id: uuid.UUID, *, lock: bool = False) -> Customer:
    row = uow.tx.execute(
        text(f"select {_SELECT} from catalog.customers c where c.id = :c and c.status <> 'deleted'"
             + (" for update of c" if lock else "")),
        {"c": customer_id},
    ).one_or_none()
    if row is None:
        raise Deny("not_found")  # unknown, another business's, or deleted (§2.1)
    return Customer(*row)


def warnings(c: Customer) -> list[dict]:
    """Shown on M9; none blocks a save (§4)."""
    out = []
    if c.gstin is not None:
        out += [{"code": w, "field": "gstin", "message": _WARNING_TEXT[w]} for w in check_gstin(c.gstin, own=False).warnings]
    if c.gstin_shared:
        out.append({"code": "gstin_shared", "field": "gstin",
                    "message": "Another customer has this GSTIN. That's fine for branches billed separately"})
    if c.gstin_state_code is not None and c.billing_state_code != c.gstin_state_code:
        out.append({"code": "billing_state_differs", "field": "billing.state_code",
                    "message": "The billing state isn't the GSTIN's state. Place of supply follows the GSTIN"})
    return out


_WARNING_TEXT = {
    "pan_shape": "Characters 3 to 12 don't look like a PAN; please re-check the GSTIN",
}


# --- Reads -------------------------------------------------------------------------


def get(uow: UnitOfWork, customer_id: uuid.UUID) -> Customer:
    return _get(uow, customer_id)


def search(uow: UnitOfWork, *, q: str | None, status: str, limit: int, offset: int) -> tuple[list[Customer], bool]:
    """Name fragment or GSTIN prefix (§6.2), the business's rows only."""
    where = ["c.status <> 'deleted'"]
    params: dict = {"limit": limit + 1, "offset": offset}
    if status in ("active", "archived"):
        where.append("c.status = :status")
        params["status"] = status
    if q and q.strip():
        needle = q.strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        where.append("(lower(c.name) like :frag or c.gstin like :prefix)")
        params.update(frag=f"%{needle}%", prefix=f"{needle.upper().replace(' ', '')}%")
    rows = uow.tx.execute(
        text(
            f"select {_SELECT} from catalog.customers c where {' and '.join(where)}"
            " order by lower(c.name), c.id limit :limit offset :offset"
        ),
        params,
    ).all()
    return [Customer(*r) for r in rows[:limit]], len(rows) > limit


# --- Checks ------------------------------------------------------------------------


def _text(value: str | None, limit: int, field: str) -> str | None:
    value = (value or "").strip()
    if not value:
        return None
    if len(value) > limit:
        raise Invalid("text_too_long", f"Use at most {limit} characters", field=field)
    return value


def _address(uow: UnitOfWork, raw: dict | None, which: str, default_state: str | None, today: date) -> dict:
    raw = raw or {}
    out = {f"{which}_{k}": _text(raw.get(k), n, f"{which}.{k}") for k, n in _LIMITS.items()}
    pin = (raw.get("pin") or "").strip() or None
    if pin is not None and not value_on(uow.tx, "address.pin_pattern", today).fullmatch(pin):
        raise Invalid("pin_invalid", "A PIN code is 6 digits and doesn't start with 0", field=f"{which}.pin")
    out[f"{which}_pin"] = pin
    state = (raw.get("state_code") or "").strip() or default_state
    if state is None:
        raise Invalid("state_code_required", "Choose the state", field=f"{which}.state_code")
    check_state(uow.tx, state, today, f"{which}.state_code")
    out[f"{which}_state_code"] = state
    return out


def _gstin(uow: UnitOfWork, raw: str | None) -> tuple[str | None, str | None]:
    if not (raw or "").strip():
        return None, None
    found = check_gstin(raw, own=False)
    if not found.ok:
        raise Invalid("gstin_invalid", gstin_message(found.errors[0], raw), field="gstin")
    profile = get_profile(uow.tx)
    if profile is not None and profile.gstin == found.normalised:
        raise Invalid("gstin_is_own", "This is your own business's GSTIN", field="gstin")
    return found.normalised, found.state_code


def _columns(uow: UnitOfWork, body: dict, today: date) -> dict:
    """The whole customer as it will be stored, or Invalid."""
    cols = {"name": checks.name(body.get("name"))}
    cols["gstin"], cols["gstin_state_code"] = _gstin(uow, body.get("gstin"))
    if cols["gstin_state_code"] is not None:
        check_state(uow.tx, cols["gstin_state_code"], today, "gstin")
    # BH-3: the state is required; it defaults to the GSTIN's (§4).
    cols.update(_address(uow, body.get("billing"), "billing", cols["gstin_state_code"], today))
    same = body.get("delivery_same_as_billing", True)
    cols["delivery_same_as_billing"] = bool(same)
    if same:
        if any((body.get("delivery") or {}).get(k) for k in ADDRESS):
            raise Invalid("delivery_not_allowed", "Leave the delivery address out when it's the billing address",
                          field="delivery")
        cols.update({f"delivery_{k}": None for k in ADDRESS})
    else:
        cols.update(_address(uow, body.get("delivery"), "delivery", None, today))
    days = body.get("credit_days", 0)
    most = int(value_on(uow.tx, "customer.credit_days_max", today))
    if isinstance(days, bool) or not isinstance(days, int) or not 0 <= days <= most:
        raise Invalid("credit_days_invalid", f"Credit days is a whole number from 0 to {most}", field="credit_days")
    cols["credit_days"] = days
    return cols


# --- Writes ------------------------------------------------------------------------


def create(uow: UnitOfWork, body: dict, today: date) -> uuid.UUID:
    cols = _columns(uow, body, today)
    customer_id = uuid7()
    names = ", ".join(cols)
    uow.tx.execute(
        text(
            f"insert into catalog.customers (id, business_id, {names}, created_by, updated_by)"
            f" values (:id, :b, {', '.join(':' + k for k in cols)}, :me, :me)"
        ),
        {"id": customer_id, "b": _business(uow), "me": _me(uow), **cols},
    )
    audit.record(uow, "customer.created", "customer", customer_id, data={})
    return customer_id


def _check_version(c: Customer, if_match: int | None) -> None:
    if if_match is None:
        raise Invalid("if_match_required", "Send the version you edited as If-Match", field="If-Match")
    if c.version != if_match:
        raise Conflict("stale_record", "Someone changed this customer since you opened it",
                       fix="Reload it and make your change again")


def update(uow: UnitOfWork, customer_id: uuid.UUID, changes: dict, if_match: int | None, today: date) -> None:
    """`billing` and `delivery` replace the whole address they name."""
    c = _get(uow, customer_id, lock=True)
    _check_version(c, if_match)
    body = {
        "name": c.name, "gstin": c.gstin, "billing": c.address("billing"),
        "delivery_same_as_billing": c.delivery_same_as_billing,
        "delivery": None if c.delivery_same_as_billing else c.address("delivery"), "credit_days": c.credit_days,
    }
    if changes.get("delivery_same_as_billing") is True and "delivery" not in changes:
        body["delivery"] = None
    body.update(changes)
    cols = _columns(uow, body, today)
    changed = {k: v for k, v in cols.items() if getattr(c, k) != v}
    if not changed:
        return
    sets = ", ".join(f"{k} = :{k}" for k in changed)
    uow.tx.execute(
        text(f"update catalog.customers set {sets}, version = version + 1, updated_at = now(), updated_by = :me"
             " where id = :c"),
        {**changed, "me": _me(uow), "c": customer_id},
    )
    audit.record(uow, "customer.updated", "customer", customer_id, data={"fields": sorted(changed)})


def set_archived(uow: UnitOfWork, customer_id: uuid.UUID, archived: bool) -> None:
    """No If-Match [RM43-7]: idempotent, changes only status, and bumps version."""
    c = _get(uow, customer_id, lock=True)
    target = "archived" if archived else "active"
    if c.status == target:
        return
    uow.tx.execute(
        text("update catalog.customers set status = :s, version = version + 1, updated_at = now(),"
             " updated_by = :me where id = :c"),
        {"s": target, "me": _me(uow), "c": customer_id},
    )
    audit.record(uow, "customer.archived" if archived else "customer.unarchived", "customer", customer_id, data={})


def delete(uow: UnitOfWork, customer_id: uuid.UUID, if_match: int | None) -> None:
    """A soft delete while never used [RM43-1, RM43-4], in one statement like products."""
    if if_match is None:
        raise Invalid("if_match_required", "Send the version you saw as If-Match", field="If-Match")
    done = uow.tx.execute(
        text(
            "update catalog.customers set status = 'deleted', version = version + 1, updated_at = now(),"
            " updated_by = :me where id = :c and version = :v and first_used_at is null and status <> 'deleted'"
            " returning id"
        ),
        {"me": _me(uow), "c": customer_id, "v": if_match},
    ).one_or_none()
    if done is None:
        c = _get(uow, customer_id)  # 404 if gone
        if c.in_use:
            raise Conflict("customer_in_use", "This customer is on invoices, so it can be archived but not deleted",
                           fix="Archive it instead")
        _check_version(c, if_match)
        raise RuntimeError("delete matched no row for an unused, current customer")
    audit.record(uow, "customer.deleted", "customer", customer_id, data={})
