"""Reads of staged runs and their rows for the preview (R1-M3, LLD-7 §8).

A run is what one file said; rows are insert-only. The labels and effect notes for a held
row come from refdata (`imports.held.<reason>.*`), never from code, so the wording can be
settled with the platform reader spec without a release. Every query filters `business_id`
as well as relying on row-level security; an unknown or foreign id is a 404.
"""

import json
import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import text

from app.modules.refdata import value_on
from platform_common.errors import Deny, Invalid
from platform_common.uow import UnitOfWork

from .readers import HOLD_REASONS

ROW_STATUSES = ("new", "already_imported", "changed", "duplicate", "conflict", "invalid", "held", "skipped_zero")
COUNT_KEYS = ROW_STATUSES
# A value fix names the field it fills; each is offered only on the hold reason that is missing that value.
FIX_ACTION = {"hsn": "enter_hsn", "state": "pick_state"}
FIX_FIELD = {"enter_hsn": "hsn", "pick_state": "state"}
FIX_REASON = {"enter_hsn": "blank_hsn", "pick_state": "unknown_state"}
SKIPPED_ZERO_LABEL = "Zero value: nothing to file."


@dataclass(frozen=True)
class Run:
    id: uuid.UUID
    upload_id: uuid.UUID | None
    section: str | None
    marketplace: str
    profile_id: str
    profile_verified: bool
    gstin: str | None
    status: str
    summary: dict
    held_by_reason: dict[str, int]  # unresolved held rows only
    set_aside: int = 0
    accepted: int = 0
    fixed: int = 0
    report_type: str = ""


@dataclass(frozen=True)
class Row:
    id: uuid.UUID
    run_id: uuid.UUID
    file_name: str
    row_number: int
    status: str
    hold_reason: str | None
    values: dict
    errors: list
    reason_label: str | None
    needs_ca_check: bool
    ca_check_note: str | None
    allowed_actions: list[dict]
    resolution: dict | None


def _business(uow: UnitOfWork) -> uuid.UUID:
    return uow.principal.business_id


LATEST = ("select distinct on (row_id) row_id, kind, note, created_at, fix_field, fix_value from imports.row_resolutions"
          " where business_id = :b order by row_id, created_at desc, id desc")


def get_run(uow: UnitOfWork, run_id: uuid.UUID) -> Run:
    r = uow.tx.execute(
        text("select r.id, r.upload_id, u.section, r.marketplace, r.profile_id, r.profile_verified, r.gstin, r.status,"
             " r.summary, r.report_type from imports.import_runs r left join imports.uploads u"
             " on u.id = r.upload_id and u.business_id = r.business_id where r.id = :r and r.business_id = :b"),
        {"r": run_id, "b": _business(uow)},
    ).one_or_none()
    if r is None:
        raise Deny("not_found")
    held: dict[str, int] = {}
    resolved = {"set_aside": 0, "accepted": 0, "fixed": 0}
    for status, reason, kind, n in uow.tx.execute(
        text(f"with latest as ({LATEST}) select w.status, w.hold_reason, l.kind, count(*)"
             " from imports.import_rows w left join latest l on l.row_id = w.id"
             " where w.run_id = :r and w.business_id = :b and w.status = 'held' group by 1, 2, 3"),
        {"r": run_id, "b": _business(uow)},
    ):
        if kind is None:
            held[reason] = held.get(reason, 0) + n
        else:
            resolved[kind] += n
    return Run(r.id, r.upload_id, r.section, r.marketplace, r.profile_id, r.profile_verified, r.gstin, r.status,
               r.summary or {}, held, resolved["set_aside"], resolved["accepted"], resolved["fixed"], r.report_type)


def counts(run: Run) -> dict[str, int]:
    """The staged counts, with `held` meaning unresolved held rows and the user's decisions
    counted on their own."""
    out = {k: int(run.summary.get(k, 0)) for k in COUNT_KEYS}
    out["held"] = sum(run.held_by_reason.values())
    out["set_aside"], out["accepted"], out["fixed"] = run.set_aside, run.accepted, run.fixed
    return out


def list_rows(uow: UnitOfWork, run_id: uuid.UUID, status: str | None, limit: int, offset: int,
              today: date) -> tuple[list[Row], bool]:
    get_run(uow, run_id)  # 404 for a run that isn't this business's
    if status is not None and status not in ROW_STATUSES:
        raise Invalid("unknown_status", "That isn't a row status.", field="status")
    found = uow.tx.execute(
        text(f"with latest as ({LATEST}) {_ROW_SELECT}"
             " where w.run_id = :r and w.business_id = :b and (cast(:s as text) is null or w.status = :s)"
             " order by w.row_number limit :n offset :o"),
        {"r": run_id, "b": _business(uow), "s": status, "n": limit + 1, "o": offset},
    ).all()
    return _build(uow, found[:limit], today), len(found) > limit


_ROW_SELECT = ("select w.id, w.run_id, r.filename, w.row_number, w.status, w.hold_reason, w.raw, w.errors,"
               " l.kind as res_kind, l.note as res_note, l.created_at as res_at, l.fix_field, l.fix_value,"
               " r.status as run_status"
               " from imports.import_rows w join imports.import_runs r on r.id = w.run_id and r.business_id = w.business_id"
               " left join latest l on l.row_id = w.id")


def get_row(uow: UnitOfWork, row_id: uuid.UUID, today: date) -> Row:
    found = uow.tx.execute(
        text(f"with latest as ({LATEST}) {_ROW_SELECT} where w.id = :w and w.business_id = :b"),
        {"w": row_id, "b": _business(uow)},
    ).all()
    if not found:
        raise Deny("not_found")
    return _build(uow, found, today)[0]


def _words(uow: UnitOfWork, key: str, today: date) -> str:
    return str(value_on(uow.tx, key, today))


def allowed_actions(uow: UnitOfWork, status: str, reason: str | None, run_status: str, today: date,
                    clash: bool = False) -> list[dict]:
    """What the user may do with a row: only a held row of a staged run. `set_aside` is always
    there; `accept` only where refdata `imports.held.<reason>.accept_allowed` is true (shipped
    false: whether an inconsistent row may be used as the file states it is the PO's and the CA's).
    A new or changed row that clashes with a live row of another file (`clash`, R1-M7 confirm check) may be set aside."""
    if run_status == "staged" and clash and status in ("new", "changed"):
        return [{"action": "set_aside", "label": _words(uow, "imports.action.set_aside.label", today),
                 "effect_note": _words(uow, "imports.action.set_aside.effect_note", today)}]
    if status != "held" or run_status != "staged" or reason not in HOLD_REASONS:
        return []
    actions = ["set_aside"] + [a for a, r in FIX_REASON.items() if r == reason]
    if bool(value_on(uow.tx, f"imports.held.{reason}.accept_allowed", today)):
        actions.append("accept")
    return [{"action": a, "label": _words(uow, f"imports.action.{a}.label", today),
             "effect_note": _words(uow, f"imports.action.{a}.effect_note", today)} for a in actions]


def _build(uow: UnitOfWork, found, today: date) -> list[Row]:
    from . import confirm

    clashing: set[uuid.UUID] = set()
    for run_id in {w.run_id for w in found if w.status in ("new", "changed") and w.run_status == "staged"}:
        clashing |= confirm.conflicting_row_ids(uow, run_id)
    labels: dict[str, tuple[str, bool]] = {}

    def held_words(reason: str) -> tuple[str, bool]:
        if reason not in labels:
            labels[reason] = (str(value_on(uow.tx, f"imports.held.{reason}.label", today)),
                              bool(value_on(uow.tx, f"imports.held.{reason}.needs_ca_check", today)))
        return labels[reason]

    rows = []
    for w in found:
        label, ca = None, False
        if w.status == "held" and w.hold_reason in HOLD_REASONS:
            label, ca = held_words(w.hold_reason)
        elif w.status == "skipped_zero":
            label = SKIPPED_ZERO_LABEL
        resolution = None
        if w.res_kind is not None:
            action = {"accepted": "accept", "set_aside": "set_aside"}.get(w.res_kind) or FIX_ACTION[w.fix_field]
            resolution = {"action": action, "note": w.res_note, "at": w.res_at,
                          "value": w.fix_value if w.res_kind == "fixed" else None}
        # A resolved row has nothing more to decide.
        actions = [] if resolution else allowed_actions(uow, w.status, w.hold_reason, w.run_status, today,
                                                        w.id in clashing)
        rows.append(Row(w.id, w.run_id, w.filename, w.row_number, w.status, w.hold_reason,
                        {k: "" if v is None else str(v) for k, v in (w.raw or {}).items()},
                        _errors(w.errors), label, ca, None, actions, resolution))
    return rows


def _errors(value) -> list[dict]:
    items = json.loads(value) if isinstance(value, str) else (value or [])
    return [{"field": e.get("field"), "code": e.get("code"), "message": e.get("message")} for e in items]


def run_ids_for(uow: UnitOfWork, upload_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[uuid.UUID]]:
    """The runs of each upload, in the order they were staged (a zip makes one per file)."""
    out: dict[uuid.UUID, list[uuid.UUID]] = {u: [] for u in upload_ids}
    if upload_ids:
        for upload_id, run_id in uow.tx.execute(
            text("select upload_id, id from imports.import_runs where business_id = :b and upload_id = any(:u)"
                 " order by uploaded_at, id"),
            {"b": _business(uow), "u": upload_ids},
        ):
            out[upload_id].append(run_id)
    return out


def discard_run(uow: UnitOfWork, run_id: uuid.UUID) -> Run:
    """A staged run is set aside and its file may be uploaded again. Repeating it is a no-op;
    a confirmed run cannot be discarded."""
    from platform_common import audit
    from platform_common.errors import Conflict

    from . import staging

    before = get_run(uow, run_id)
    try:
        staging.discard(uow.tx, business_id=_business(uow), run_id=run_id)
    except staging.RunStateError:
        raise Conflict("run_not_staged", "This file has already been used, so it can't be discarded.") from None
    if before.status == "staged":
        audit.record(uow, "imports.run_discarded", "import_run", run_id,
                     data={"run_id": str(run_id), "section": before.section})
    return get_run(uow, run_id)


def _checked_value(uow: UnitOfWork, action: str, value: str | None, today: date) -> str:
    """The value a user enters for a fix, checked for shape only (never which HSN or state is right):
    an HSN in the shape refdata `hsn.pattern` allows, a state from the refdata state list (by code)."""
    from app.modules.refdata import state_codes

    text_value = (value or "").strip()
    if not text_value:
        raise Invalid("value_required", "Enter a value.", field="value")
    if action == "enter_hsn":
        if not value_on(uow.tx, "hsn.pattern", today).fullmatch(text_value):
            # Wording mirrors refdata `hsn.pattern` (4, 6 or 8 digits); update it if that pattern changes.
            raise Invalid("hsn_invalid", "That isn't a valid HSN. Use 4, 6 or 8 digits, with no spaces.", field="value")
        return text_value
    codes = {code for code, _ in state_codes(uow.tx, today)}
    if text_value not in codes:
        raise Invalid("state_unknown", "Choose a state from the list.", field="value")
    return text_value


def resolve(uow: UnitOfWork, row_id: uuid.UUID, action: str, note: str, today: date, value: str | None = None) -> Row:
    """Record the user's decision on a held row (insert-only; the latest decision wins).
    404 for another business's row; 409 once the run is no longer staged; 422 for an action
    the row doesn't offer, a blank note, or a bad value for a fix. The same decision twice records
    nothing new. A fix (`enter_hsn`, `pick_state`) keeps the value chosen beside the decision; the row as the
    file said it is never changed."""
    from platform_common import audit
    from platform_common.errors import Conflict
    from platform_common.ids import uuid7

    note = (note or "").strip()
    row = get_row(uow, row_id, today)
    run = get_run(uow, row.run_id)
    if run.status != "staged":
        raise Conflict("run_not_staged", "This file's preview has been closed, so its rows can't be changed.")
    if action not in ("set_aside", "accept", *FIX_FIELD):
        raise Invalid("action_not_allowed", "That isn't something you can do with this row.", field="action")
    if not note:
        raise Invalid("note_required", "Add a note saying why.", field="note")
    if len(note) > 500:
        raise Invalid("note_too_long", "Keep the note to 500 characters.", field="note")
    kind = {"accept": "accepted", "set_aside": "set_aside"}.get(action, "fixed")
    if row.resolution is not None:
        same = row.resolution["action"] == action and (kind != "fixed" or row.resolution["value"] == (value or "").strip())
        if same:
            return row  # already decided this way
        raise Invalid("action_not_allowed", "This row has already been decided.", field="action")
    if action not in [a["action"] for a in row.allowed_actions]:
        raise Invalid("action_not_allowed", "That isn't something you can do with this row.", field="action")
    fix_value = _checked_value(uow, action, value, today) if kind == "fixed" else None
    # One decision per row is held by the unique index; of two simultaneous decisions the second
    # inserts nothing (ON CONFLICT waits for the first to commit) and is answered as the code path
    # answers a row that is already decided.
    inserted = uow.tx.execute(
        text("insert into imports.row_resolutions (id, business_id, row_id, kind, note, created_by, fix_field, fix_value)"
             " values (:i, :b, :r, :k, :n, :u, :ff, :fv) on conflict (row_id) do nothing returning id"),
        {"i": uuid7(), "b": _business(uow), "r": row_id, "k": kind, "n": note, "u": uow.principal.user_id,
         "ff": FIX_FIELD.get(action), "fv": fix_value},
    ).first()
    if inserted is None:
        won = uow.tx.execute(
            text("select kind, fix_field, fix_value from imports.row_resolutions where row_id = :r"), {"r": row_id}
        ).one()
        if won.kind == kind and (kind != "fixed" or (won.fix_field, won.fix_value) == (FIX_FIELD.get(action), fix_value)):
            return get_row(uow, row_id, today)
        raise Invalid("action_not_allowed", "This row has already been decided.", field="action")
    event = {"accepted": "imports.row_accepted", "set_aside": "imports.row_set_aside",
             "fixed": "imports.row_fixed"}[kind]
    audit.record(uow, event, "import_row", row_id, reason=note,
                 data={"run_id": str(row.run_id), "row_id": str(row_id), "hold_reason": row.hold_reason,
                       **({"field": FIX_FIELD[action]} if kind == "fixed" else {})})
    return get_row(uow, row_id, today)
