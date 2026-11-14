"""What stands between a staged run and confirming it (R1-M7 slice 1, r1-m7-gstr1-build.md).

Read-only: `check` writes nothing and decides nothing about tax. It lists the reasons confirming is
refused, each with a count and the row numbers (never a cell value, a GSTIN or a document number), so
the user can fix the file or decide the rows and look again. Wording comes from refdata
`imports.confirm.<code>.label`. The gates:

- the run is staged, and its layout is verified (LLD-7 L7-13; a local demo may open that gate, below);
- the profile names the date that puts a row in a return (`imports.profile.<id>.period_field`);
  Flipkart and Meesho have none until CA item 1 is answered, so they are refused;
- every held row is decided, and no row is invalid or in conflict (nothing is left out silently);
- the lines of one document agree on its date, original invoice, buyer GSTIN and total;
- no live row of an earlier or parallel file has the same cross-run key and different values;
- no included row has fewer HSN digits than the rule for its date allows.

Included rows are the new and changed rows plus held rows the user accepted or fixed, never a row set
aside. A fix replaces the HSN for the check only; the row itself is never changed.
"""

import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy import text

from app.modules.business.interface import fy_of, hsn_band_missing, hsn_min_digits
from app.modules.filing.interface import assert_period_open, target_return_instance
from app.modules.refdata import first_valid_from, state_codes, value_on
from platform_common import audit
from platform_common.auth import debug_env
from platform_common.clock import Clock
from platform_common.errors import Conflict, Deny, Invalid
from platform_common.ids import uuid7
from platform_common.uow import UnitOfWork

from . import documents, runs, staging
from .readers import reader_for_run

ROW_LIST_LIMIT = 20
LEFT_OUT_STATUSES = ("already_imported", "duplicate", "skipped_zero")
_NAME = re.compile(r"[a-z][a-z0-9_]*")


@dataclass(frozen=True)
class Blocker:
    code: str
    label: str
    count: int
    rows: tuple[int, ...] = ()  # row numbers, the first ROW_LIST_LIMIT
    ca_items: tuple[str, ...] = ()  # CA question-sheet ids this blocker waits on (team/program-lead/ca-question-sheet-v1.md)


@dataclass(frozen=True)
class Note:
    code: str
    label: str


@dataclass(frozen=True)
class ConfirmCheck:
    run_id: uuid.UUID
    can_confirm: bool
    included: int
    changed: int  # included rows that differ from a confirmed earlier file (their accept or skip is chosen at confirm)
    left_out: dict[str, int] = field(default_factory=dict)
    blockers: tuple[Blocker, ...] = ()
    notes: tuple[Note, ...] = ()


@dataclass(frozen=True)
class _Row:
    id: uuid.UUID
    number: int
    status: str
    hold_reason: str | None
    values: dict
    content_hash: str | None
    resolution: str | None
    fix_field: str | None
    fix_value: str | None
    dedup_key: str | None = None


def demo_verified() -> bool:
    """A local demo (`DEMO_READERS=1`, debug environment only, never on Lambda) opens the verified-layout
    gate so synthetic files can be taken end to end. Production profiles stay unverified."""
    return os.environ.get("DEMO_READERS") == "1" and debug_env()


def _label(uow: UnitOfWork, code: str, today: date) -> str:
    return str(value_on(uow.tx, f"imports.confirm.{code}.label", today))


def _load(uow: UnitOfWork, run_id: uuid.UUID) -> list[_Row]:
    found = uow.tx.execute(
        text(f"with latest as ({runs.LATEST})"
             " select w.id, w.row_number, w.status, w.hold_reason, w.normalized, w.content_hash,"
             " l.kind, l.fix_field, l.fix_value, w.dedup_key from imports.import_rows w left join latest l on l.row_id = w.id"
             " where w.run_id = :r and w.business_id = :b order by w.row_number"),
        {"r": run_id, "b": uow.principal.business_id},
    ).all()
    return [_Row(w.id, w.row_number, w.status, w.hold_reason, w.normalized or {}, w.content_hash, w.kind,
                 w.fix_field, w.fix_value, w.dedup_key) for w in found]


def _period_fields(uow: UnitOfWork, reader, today: date) -> tuple[str, ...] | None:
    key = f"imports.profile.{reader.id}.period_field"
    if first_valid_from(uow.tx, key) is None:
        return None
    return tuple(f.strip() for f in str(value_on(uow.tx, key, today)).split(",") if f.strip())


def _date_of(values: dict, fields: tuple[str, ...]) -> date | None:
    for name in fields:
        raw = values.get(name)
        if raw:
            try:
                return date.fromisoformat(str(raw).partition("T")[0])
            except ValueError:
                return None
    return None


def _same(a, b) -> bool:
    """Two cells agree when equal as numbers (if both read as numbers) or as trimmed, case-folded text."""
    a, b = ("" if a is None else str(a).strip()), ("" if b is None else str(b).strip())
    try:
        return Decimal(a) == Decimal(b)
    except InvalidOperation:
        return a.casefold() == b.casefold()


def _treatment_confirmed(uow: UnitOfWork, reader, today: date) -> bool:
    """How this report enters the return: a reviewed refdata flag per profile (the CA's answers), and a mapper
    in code. Own invoices are confirmed; the platform reports are not until the CA answers."""
    if reader is None or not getattr(reader, "maps_documents", False):
        return False
    key = f"imports.profile.{reader.id}.treatment_confirmed"
    return first_valid_from(uow.tx, key) is not None and bool(value_on(uow.tx, key, today))


def _open_ca_items(uow: UnitOfWork, reader, today: date) -> tuple[str, ...]:
    if reader is None:
        return ()
    key = f"imports.profile.{reader.id}.open_ca_items"
    if first_valid_from(uow.tx, key) is None:
        return ()
    return tuple(i.strip() for i in str(value_on(uow.tx, key, today)).split(",") if i.strip())


def _states(uow: UnitOfWork, today: date) -> dict[str, str]:
    out: dict[str, str] = {}
    for code, name in state_codes(uow.tx, today):
        out[code.casefold()] = code
        out[" ".join(name.split()).casefold()] = code
    return out


def _mapped(uow: UnitOfWork, reader, rows: list[_Row], today: date):
    """(documents, problems) from the included rows, or None where the report's treatment is not confirmed."""
    if reader is None or not getattr(reader, "maps_documents", False):
        return None
    items = [(r.number, r.id, r.values, r.dedup_key or "",
              r.fix_value if r.resolution == "fixed" and r.fix_field == "hsn" else None,
              r.fix_value if r.resolution == "fixed" and r.fix_field == "state" else None)
             for r in rows if _included(r)]
    return documents.own_documents(items, fy_of, _states(uow, today))


def _existing(uow: UnitOfWork, docs: list[documents.Doc]) -> dict[tuple, object]:
    """Confirmed documents with the identity of any of `docs`, by (gstin, kind, fy, folded number)."""
    if not docs:
        return {}
    found = uow.tx.execute(
        text("select d.* from imports.documents d join unnest(cast(:g as text[]), cast(:k as text[]),"
             " cast(:f as text[]), cast(:n as text[])) as t(g, k, f, n)"
             " on d.gstin = t.g and d.doc_kind = t.k and d.fy = t.f and d.doc_key = t.n"
             " where d.business_id = :b"),
        {"b": uow.principal.business_id, "g": [d.gstin for d in docs], "k": [d.kind for d in docs],
         "f": [fy_of(d.date) for d in docs], "n": [d.key for d in docs]},
    ).all()
    return {(e.gstin, e.doc_kind, e.fy, e.doc_key): e for e in found}


def _identity(doc: documents.Doc) -> tuple:
    return (doc.gstin, doc.kind, fy_of(doc.date), doc.key)


def _same_document(doc: documents.Doc, e) -> bool:
    return (doc.date == e.doc_date and doc.pos == e.pos_state_code and (doc.buyer_gstin or "") == (e.counterparty_gstin or "")
            and documents.fold(doc.original_number) == documents.fold(e.original_doc_number)
            and doc.original_date == e.original_doc_date)


def _included(row: _Row) -> bool:
    if row.resolution == "set_aside":
        return False
    if row.status == "held":
        return row.resolution in ("accepted", "fixed")
    return row.status in ("new", "changed")


def _folded(value) -> str:
    return "".join(str(value or "").split()).upper()


def disagreeing_rows(rows: list[_Row], key: tuple[str, ...], agree: tuple[str, ...], period: tuple[str, ...]) -> list[int]:
    """Row numbers of documents whose included lines differ on one of `agree`. A document is its `key` plus
    the financial year of its date, so a number reused in another year is another document."""
    groups: dict[tuple, list[_Row]] = {}
    for row in rows:
        if not _included(row):
            continue
        d = _date_of(row.values, period)
        fy = None if d is None else fy_of(d)
        groups.setdefault((*(_folded(row.values.get(k)) for k in key), fy), []).append(row)
    bad: list[int] = []
    for lines in groups.values():
        first = lines[0].values
        if any(not _same(first.get(f), r.values.get(f)) for r in lines[1:] for f in agree):
            bad.extend(r.number for r in lines)
    return sorted(bad)


def _kv(value) -> str:
    """A cross-run key part as text. A blank part is a value like any other: a row with a blank
    `order_date` must clash with another file's row with a blank one, not slip past the gate."""
    return "" if value is None else str(value).strip()


def _other_rows(uow: UnitOfWork, run, key: tuple[str, ...], mine: list[_Row]):
    for name in key:
        if not _NAME.fullmatch(name):
            raise ValueError(f"bad cross-run field name {name!r}")
    params: dict = {"b": uow.principal.business_id, "m": run.marketplace, "t": run.report_type, "r": run.id}
    wheres = []
    for i, name in enumerate(key):
        params[f"v{i}"] = sorted({_kv(r.values.get(name)) for r in mine})
        wheres.append(f" and coalesce(btrim(w.normalized ->> '{name}'), '') = any(:v{i})")
    return uow.tx.execute(
        text(f"with latest as ({runs.LATEST})"
             " select w.normalized, w.content_hash from imports.import_rows w"
             " join imports.import_runs r on r.id = w.run_id and r.business_id = w.business_id"
             " left join latest l on l.row_id = w.id"
             " where w.business_id = :b and r.marketplace = :m and r.report_type = :t and r.id <> :r"
             " and r.status in ('staged', 'confirmed') and w.status in ('new', 'changed', 'already_imported', 'held')"
             " and coalesce(l.kind, '') <> 'set_aside'" + "".join(wheres)),
        params,
    ).all()


def conflicting_rows(uow: UnitOfWork, run, reader, rows: list[_Row]) -> dict[uuid.UUID, int]:
    """This run's included rows (id -> row number) that share the reader's cross-run key with a live row of
    another file but differ in values. The older file's row is not offered a decision here: a staged file is
    discarded, and a confirmed row stays."""
    key = getattr(reader, "cross_run_key", None)
    mine = [r for r in rows if _included(r) and r.content_hash]
    if not key or not mine:
        return {}
    theirs: dict[tuple, set[str]] = {}
    for other in _other_rows(uow, run, key, mine):
        theirs.setdefault(tuple(_kv(other.normalized.get(k)) for k in key), set()).add(other.content_hash)
    return {r.id: r.number for r in mine
            if (hashes := theirs.get(tuple(_kv(r.values.get(k)) for k in key))) and not hashes <= {r.content_hash}}


def conflicting_row_ids(uow: UnitOfWork, run_id: uuid.UUID) -> set[uuid.UUID]:
    """For the row list: which rows of a staged run may be set aside because of a cross-run clash."""
    run = runs.get_run(uow, run_id)
    reader = reader_for_run(run.section, run.report_type)
    if run.status != "staged" or reader is None or not getattr(reader, "cross_run_key", None):
        return set()
    return set(conflicting_rows(uow, run, reader, _load(uow, run_id)))


def check(uow: UnitOfWork, run_id: uuid.UUID, today: date) -> ConfirmCheck:
    run = runs.get_run(uow, run_id)  # a run of another business is a 404
    if run.status != "staged":
        raise Conflict("run_not_staged", "This file has already been used, so it can't be confirmed.")
    reader = reader_for_run(run.section, run.report_type)
    rows = _load(uow, run_id)
    blockers: list[Blocker] = []

    def block(code: str, numbers: list[int] | None = None, ca_items: tuple[str, ...] = ()) -> None:
        count = 1 if numbers is None else len(numbers)
        blockers.append(Blocker(code, _label(uow, code, today), count, tuple((numbers or [])[:ROW_LIST_LIMIT]), ca_items))

    if not (run.profile_verified or demo_verified()):
        block("profile_not_verified")
    period = None if reader is None else _period_fields(uow, reader, today)
    if period is None:
        block("period_date_unconfirmed")

    undecided = [r.number for r in rows if r.status == "held" and r.resolution is None]
    invalid = [r.number for r in rows if r.status == "invalid"]
    clashing = [r.number for r in rows if r.status == "conflict"]
    for code, numbers in (("rows_undecided", undecided), ("rows_invalid", invalid), ("rows_conflict", clashing)):
        if numbers:
            block(code, numbers)

    included = [r for r in rows if _included(r)]
    if period is not None and (undated := [r.number for r in included if _date_of(r.values, period) is None]):
        block("rows_undated", undated)  # a row with no readable date can't be assigned to a return
    if reader is not None:
        key, agree = getattr(reader, "document_key", None), getattr(reader, "document_agree", None)
        if key and agree and period is not None and (numbers := disagreeing_rows(rows, key, agree, period)):
            block("document_rows_disagree", numbers)
        if clash := conflicting_rows(uow, run, reader, rows):  # reported even while the period date is open
            block("rows_conflict_across_runs", sorted(clash.values()))

    mapped = _mapped(uow, reader, rows, today) if _treatment_confirmed(uow, reader, today) else None
    if reader is not None and mapped is None:
        block("treatment_unconfirmed", ca_items=_open_ca_items(uow, reader, today))
    elif mapped is not None:
        docs, problems = mapped
        for code, numbers in problems:
            block(code, numbers)
        existing = _existing(uow, docs)
        changed_ids = {r.id for r in rows if r.status == "changed"}
        differs = sorted(ln.row_number for d in docs if (e := existing.get(_identity(d))) is not None
                         and not _same_document(d, e) and any(ln.row_id not in changed_ids for ln in d.lines)
                         for ln in d.lines)
        if differs:
            block("document_differs_from_confirmed", differs)

    notes: list[Note] = []
    if period is not None:
        short: list[int] = []
        digits: dict[date, int] = {}
        band_missing = False
        for r in included:
            d = _date_of(r.values, period)
            if d is None:
                continue
            if d not in digits:
                digits[d] = hsn_min_digits(uow.tx, d)
                band_missing = band_missing or hsn_band_missing(uow.tx, d) is not None
            hsn = r.fix_value if (r.resolution == "fixed" and r.fix_field == "hsn") else r.values.get("hsn")
            if len(str(hsn or "")) < digits[d]:
                short.append(r.number)
        if short:
            block("hsn_too_short", short)
        if band_missing:
            notes.append(Note("hsn_band_missing", _label(uow, "hsn_band_missing", today)))

    left_out = {"set_aside": sum(1 for r in rows if r.resolution == "set_aside")}
    for status in LEFT_OUT_STATUSES:
        left_out[status] = sum(1 for r in rows if r.status == status and r.resolution != "set_aside")
    return ConfirmCheck(
        run_id=run_id, can_confirm=not blockers, included=len(included),
        changed=sum(1 for r in included if r.status == "changed"), left_out=left_out,
        blockers=tuple(blockers), notes=tuple(notes),
    )


@dataclass(frozen=True)
class Confirmed:
    run_id: uuid.UUID
    documents: int
    lines: int
    accepted_changes: int
    skipped_changes: int


_ACCEPT_NOTE = "Accepted the changed values when confirming."
_SKIP_NOTE = "Kept the earlier file's values when confirming."
_INSERT_DOC = text(
    "insert into imports.documents (id, business_id, gstin, source, doc_kind, doc_number, doc_key, fy, doc_date,"
    " original_doc_number, original_doc_date, original_not_in_app, supply_class, counterparty_gstin, pos_state_code,"
    " is_inter_state, doc_total, return_instance_id, return_period, first_run_id, created_by)"
    " values (:id, :b, :gstin, 'own_upload', :kind, :number, :key, :fy, :date, :on, :od, :nia, :cls, :buyer, :pos,"
    " :inter, :total, :inst, :period, :run, :by)")
_INSERT_LINE = text(
    "insert into imports.document_lines (id, business_id, document_id, source_row_id, line_key, line_pos, hsn, hsn_from,"
    " unit, quantity, rate, taxable_value, igst, cgst, sgst, cess, supersedes, created_by)"
    " values (:id, :b, :doc, :row, :key, :pos, :hsn, :from, :unit, :qty, :rate, :taxable, :igst, :cgst, :sgst, :cess,"
    " :sup, :by)")


def _resolve_changed(uow: UnitOfWork, rows: list[_Row], choices: dict[uuid.UUID, str]) -> tuple[list[_Row], int, int]:
    """The changed rows each need accept or skip; both are recorded as decisions (insert-only, with a note)."""
    changed = [r for r in rows if _included(r) and r.status == "changed"]
    ids = {r.id for r in changed}
    if set(choices) - ids or any(choices.get(r.id) not in ("accept", "skip") for r in changed):
        raise Invalid("changes_undecided", "Choose to accept or skip each row that changed since the earlier file.",
                      field="changed")
    for r in changed:
        accept = choices[r.id] == "accept"
        uow.tx.execute(
            text("insert into imports.row_resolutions (id, business_id, row_id, kind, note, created_by)"
                 " values (:i, :b, :r, :k, :n, :u) on conflict (row_id) do nothing"),
            {"i": uuid7(), "b": uow.principal.business_id, "r": r.id, "k": "accepted" if accept else "set_aside",
             "n": _ACCEPT_NOTE if accept else _SKIP_NOTE, "u": uow.principal.user_id})
    skipped = {r.id for r in changed if choices[r.id] == "skip"}
    kept = [r for r in rows if r.id not in skipped]
    return kept, len(ids) - len(skipped), len(skipped)


def confirm(uow: UnitOfWork, run_id: uuid.UUID, choices: dict[uuid.UUID, str], clock: Clock) -> Confirmed:
    """Writes a staged run's included rows as confirmed documents and lines, assigns each new document to its
    return once, records the decisions and marks the run confirmed. One transaction: a locked period, a stale
    run or any refusal leaves nothing behind. Repeating it on a confirmed run is a 409."""
    today = clock.today()
    business = uow.principal.business_id
    by = uow.principal.user_id
    # Lock first, then check: every gate (including the cross-file clash) is re-run under the run's row lock and
    # the report type's lock, so another file confirmed between a check and this call is seen, not missed.
    if uow.tx.execute(text("select 1 from imports.import_runs where id = :r and business_id = :b for update"),
                      {"r": run_id, "b": business}).first() is None:
        raise Deny("not_found")
    run = runs.get_run(uow, run_id)
    staging._lock_report_type(uow.tx, business, run.marketplace, run.report_type)  # noqa: SLF001
    chk = check(uow, run_id, today)
    if not chk.can_confirm:
        raise Conflict("confirm_blocked", "This file can't be confirmed yet. See what is in the way and try again.")
    reader = reader_for_run(run.section, run.report_type)
    rows = _load(uow, run_id)
    kept, accepted, skipped = _resolve_changed(uow, rows, choices)
    docs, _ = _mapped(uow, reader, kept, today) or ([], [])  # check() has refused any report without a mapper
    existing = _existing(uow, docs)
    changed_ids = {r.id for r in kept if r.status == "changed"}
    new_docs = 0
    new_lines = 0
    for doc in sorted(docs, key=lambda d: d.kind != "invoice"):  # invoices first, so a note finds its original
        found = existing.get(_identity(doc))
        if found is None:
            found_id = _insert_document(uow, doc, run_id, today, by)
            new_docs += 1
            pos = 0
        else:
            if any(ln.row_id in changed_ids for ln in doc.lines) and not _same_document(doc, found):
                raise Conflict("change_needs_correction_note",
                               _label(uow, "change_needs_correction_note", today))
            if found.return_instance_id is not None:
                assert_period_open(uow.tx, found.return_instance_id)
            found_id = found.id
            pos = uow.tx.execute(text("select coalesce(max(line_pos), 0) from imports.document_lines"
                                      " where business_id = :b and document_id = :d"), {"b": business, "d": found_id}).scalar_one()
        for ln in doc.lines:
            pos += 1
            prior = None
            if ln.row_id in changed_ids and found is not None:
                prior = uow.tx.execute(
                    text("select l.id from imports.document_lines l where l.business_id = :b and l.document_id = :d"
                         " and l.line_key = :k and not exists (select 1 from imports.document_lines s"
                         " where s.supersedes = l.id)"), {"b": business, "d": found_id, "k": ln.line_key}).scalar()
            uow.tx.execute(_INSERT_LINE, {
                "id": uuid7(), "b": business, "doc": found_id, "row": ln.row_id, "key": ln.line_key, "pos": pos,
                "hsn": ln.hsn, "from": ln.hsn_from, "unit": ln.unit, "qty": ln.quantity, "rate": ln.rate,
                "taxable": ln.taxable_value, "igst": ln.igst, "cgst": ln.cgst, "sgst": ln.sgst, "cess": ln.cess,
                "sup": prior, "by": by})
            new_lines += 1
    try:
        staging.confirm(uow.tx, business_id=business, run_id=run_id, user_id=by, clock=clock)
    except staging.StaleRun:
        raise Conflict("run_stale", "Another file was confirmed in the meantime. Discard this one and upload it again.") from None
    audit.record(uow, "imports.confirmed", "import_run", run_id,
                 data={"run_id": str(run_id), "section": run.section, "documents": new_docs, "lines": new_lines,
                       "accepted_changes": accepted, "skipped_changes": skipped})
    return Confirmed(run_id, new_docs, new_lines, accepted, skipped)


def _insert_document(uow: UnitOfWork, doc: documents.Doc, run_id: uuid.UUID, today: date, by) -> uuid.UUID:
    """A new document: classified, assigned to its return (a locked period refuses the whole confirm), written."""
    original_class, original_found = None, False
    if doc.kind == "credit_note" and doc.original_number and doc.original_date:
        found = uow.tx.execute(
            text("select supply_class from imports.documents where business_id = :b and gstin = :g and"
                 " doc_kind = 'invoice' and fy = :f and doc_key = :k"),
            {"b": uow.principal.business_id, "g": doc.gstin, "f": fy_of(doc.original_date),
             "k": documents.fold(doc.original_number)}).first()
        original_found = found is not None
        original_class = None if found is None else found.supply_class
    cls = documents.supply_class(doc.kind, doc.buyer_gstin, doc.inter_state, doc.total,
                                 value_on(uow.tx, "gstr1.b2cl_threshold", doc.date), original_class)
    inst = None
    if cls is not None:  # a debit note has no return yet
        inst = target_return_instance(uow.tx, doc.gstin, "credit_note" if doc.kind == "credit_note" else "invoice",
                                      doc.date, cls, None, taxable_value=doc.taxable, today=today)
    doc_id = uuid7()
    uow.tx.execute(_INSERT_DOC, {
        "id": doc_id, "b": uow.principal.business_id, "gstin": doc.gstin, "kind": doc.kind, "number": doc.number,
        "key": doc.key, "fy": fy_of(doc.date), "date": doc.date, "on": doc.original_number, "od": doc.original_date,
        "nia": doc.kind == "credit_note" and bool(doc.original_number) and not original_found,
        "cls": cls, "buyer": doc.buyer_gstin, "pos": doc.pos, "inter": doc.inter_state, "total": doc.total,
        "inst": None if inst is None else inst.id, "period": None if inst is None else inst.period,
        "run": run_id, "by": by})
    return doc_id


def none_this_month(uow: UnitOfWork, section: str, month: str, clock: Clock) -> date:
    """The user says a section has no sales in a calendar month. Insert-only; saying it twice changes nothing.
    The month is a calendar month of the filing period, never the coverage `months` label (D-052)."""
    from .sections import ENABLED

    if not ENABLED.get(section):
        raise Invalid("unknown_section", "That isn't an upload section.", field="section")
    try:
        first = date.fromisoformat(f"{month}-01")
    except ValueError:
        raise Invalid("invalid_month", "Choose a month, like 2026-10.", field="month") from None
    if first > clock.today().replace(day=1):
        raise Invalid("month_in_future", "That month hasn't started yet.", field="month")
    inserted = uow.tx.execute(
        text("insert into imports.period_confirmations (id, business_id, section, month, created_by)"
             " values (:i, :b, :s, :m, :u) on conflict (business_id, section, month) do nothing returning id"),
        {"i": uuid7(), "b": uow.principal.business_id, "s": section, "m": first, "u": uow.principal.user_id}).first()
    if inserted is not None:
        audit.record(uow, "imports.none_this_month", "import_period_confirmation", inserted.id,
                     data={"section": section, "month": month})
    return first


def list_none_this_month(uow: UnitOfWork) -> list[tuple[str, date]]:
    return [(r.section, r.month) for r in uow.tx.execute(
        text("select section, month from imports.period_confirmations where business_id = :b order by month, section"),
        {"b": uow.principal.business_id})]
