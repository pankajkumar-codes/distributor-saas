"""Table 13 of GSTR-1, documents issued (docs/TABLE13_SPEC.md, issue #353).

The portal will not generate the summary while Tables 4 to 10, 14 or 15 hold data and Table 13 is empty. This module derives the
series the person probably issued from the documents of a return, checks the rows the person confirms, stores each
confirmation as a new insert-only version, and hands the counted rows to the file and the snapshot.

What is decided here, and what is not (spec sections 3 and 9):
- Only the seller's own series are suggested: own live documents and the seller's own invoices uploaded from other software.
  Marketplace-issued numbers are not in `filing.v_supply_lines`, so they are never suggested; the person adds them as a manual
  row if the CA says they count (T13-1). A practice document is never in the view, so never here (A3).
- Cancelled counts of a suggested series come from the app's own cancellations (#456, sales.v_cancelled_documents): a
  cancelled live invoice is counted in Total and Cancelled, never in Tables 4 to 12. Cancellations made outside the app
  are the person's to enter (A4).
- Nothing here says what the portal accepts. The checks of a row are ours (spec section 6), not the portal's.
- Counts are integers; there is no money in this table, and no float anywhere.
"""

import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text

from platform_common import audit
from platform_common.errors import Conflict, Invalid
from platform_common.ids import uuid7
from platform_common.uow import BusinessUoW

from .build import ReturnBuild
from .periods import ReturnInstance
from .snapshots import lock_instance

# The offline tool's master list of document natures, in its order: the number is the `doc_num` of the file.
NATURES = dict(enumerate((
    "Invoices for outward supply",
    "Invoices for inward supply from an unregistered person",
    "Revised invoice",
    "Debit note",
    "Credit note",
    "Receipt voucher",
    "Payment voucher",
    "Refund voucher",
    "Delivery challan for job work",
    "Delivery challan for supply on approval",
    "Delivery challan in case of liquid gas",
    "Delivery challan in other cases",
), 1))  # fmt: skip
DOC_KIND_NATURE = {"invoice": 1, "debit_note": 4, "credit_note": 5}
SOURCES = ("own_live", "uploaded_own", "marketplace", "manual")
MAX_LEN = 16
_CHARS = re.compile(r"^[A-Za-z0-9/-]+$")
_TAIL = re.compile(r"(\d+)$")
# Tables whose data makes Table 13 mandatory on the portal (the build holds 4 to 10; Tables 14 and 15 are not built yet).
DATA_SECTIONS = ("b2b", "b2cl", "b2cs", "cdnr", "cdnur")


@dataclass(frozen=True)
class DocRow:
    nature: int
    from_no: str
    to_no: str
    total: int
    cancelled: int
    source: str = "manual"
    counted: bool = True
    missing: int = 0  # numbers inside the range that no document of ours has; a hint for the screen, never stored

    @property
    def net_issue(self) -> int:
        return self.total - self.cancelled

    @property
    def key(self) -> tuple[int, str, str]:
        return (self.nature, self.from_no, self.to_no)


def split_number(number: str) -> tuple[str, str]:
    """The number's text before its final run of digits, and that run. `INV/26-27/0001` is ('INV/26-27/', '0001')."""
    m = _TAIL.search(number)
    return (number[: m.start()], m.group(1)) if m else (number, "")


def has_data(build: ReturnBuild) -> bool:
    return any(getattr(build.sections, name) for name in DATA_SECTIONS)


# -- Suggestions ------------------------------------------------------------------------------------------------


def suggest(lines, cancelled=()) -> list[DocRow]:
    """One row per (nature, series) among the documents of the return. A series is the number without its final digits plus the
    number of those digits, so `INV/001` and `INV/0001` are two series (spec 4.3). `total` counts distinct numbers, not the
    range. Lines of one document count once. `cancelled` (own live documents cancelled in the app, #456) count in the
    series' total and in its cancelled count."""
    found: dict[tuple, dict[str, bool]] = {}  # (nature, prefix, width) -> number -> was it an own live document
    gone: dict[tuple, set[str]] = {}
    for ln in lines:
        nature = DOC_KIND_NATURE.get(ln.doc_kind)
        number = ln.doc_number.strip()
        if nature is None or not number:
            continue
        prefix, digits = split_number(number)
        live = ln.source_ref == ln.doc_number  # sales publishes the number as its reference; an upload gives file and row
        found.setdefault((nature, prefix, len(digits)), {})[number] = live
    for c in cancelled:
        nature = DOC_KIND_NATURE.get(c.doc_kind)
        number = c.doc_number.strip()
        if nature is None or not number:
            continue
        prefix, digits = split_number(number)
        found.setdefault((nature, prefix, len(digits)), {})[number] = True
        gone.setdefault((nature, prefix, len(digits)), set()).add(number)
    out = []
    for (nature, prefix, width), numbers in found.items():
        ordered = sorted(numbers, key=lambda n: (int(split_number(n)[1] or 0), n))
        lo, hi = ordered[0], ordered[-1]
        span = int(split_number(hi)[1] or 0) - int(split_number(lo)[1] or 0) + 1 if width else 1
        out.append(DocRow(nature, lo, hi, len(ordered), len(gone.get((nature, prefix, width), ())),
                          "own_live" if all(numbers.values()) else "uploaded_own",
                          True, max(span - len(ordered), 0)))  # fmt: skip
    return sorted(out, key=lambda r: (r.nature, r.from_no, r.to_no))


# -- Checks of a row (ours, spec section 6) ---------------------------------------------------------------------


class RowInvalid(ValueError):
    """A row the person sent cannot be used; `str()` is the plain reason."""


def validate(rows: list[DocRow]) -> None:
    ranges: dict[tuple[str, int], list[tuple[int, int, int]]] = {}
    for n, r in enumerate(rows, 1):
        where = f"Row {n}"
        if r.nature not in NATURES:
            raise RowInvalid(f"{where}: choose a kind of document from the list.")
        for label, value in (("from", r.from_no), ("to", r.to_no)):
            if not value or len(value) > MAX_LEN or not _CHARS.match(value):
                raise RowInvalid(f"{where}: the {label} number must be 1 to {MAX_LEN} letters, digits, - or /.")
        if r.total < 0 or r.cancelled < 0 or r.cancelled > r.total:
            raise RowInvalid(f"{where}: cancelled cannot be more than the total, and neither can be below zero.")
        (p1, d1), (p2, d2) = split_number(r.from_no), split_number(r.to_no)
        if not d1 or not d2:
            if r.from_no != r.to_no:
                raise RowInvalid(f"{where}: the from and to numbers must end in digits of the same length.")
            lo = hi = 0
        else:
            if p1 != p2 or len(d1) != len(d2):
                raise RowInvalid(f"{where}: the from and to numbers must start the same way and have the same number of digits.")
            lo, hi = int(d1), int(d2)
            if hi < lo:
                raise RowInvalid(f"{where}: the to number is before the from number.")
            if r.total > hi - lo + 1:
                raise RowInvalid(f"{where}: the total is more than the numbers between from and to.")
        ranges.setdefault((p1, len(d1)), []).append((lo, hi, n - 1))
    for spans in ranges.values():
        spans.sort()
        for (_, hi_a, ia), (lo_b, _, ib) in zip(spans, spans[1:], strict=False):
            if lo_b <= hi_a:
                same = rows[ia].nature == rows[ib].nature
                raise RowInvalid(
                    f"Rows {ia + 1} and {ib + 1}: the numbers overlap" + (
                        "." if same else ", and one number cannot be two kinds of document."))  # fmt: skip


# -- Store: insert-only versions per return ---------------------------------------------------------------------


@dataclass(frozen=True)
class Confirmation:
    id: uuid.UUID
    version: int
    fingerprint: str
    at: datetime
    rows: tuple[DocRow, ...]


def _hash(fingerprint: str, rows: list[DocRow]) -> str:
    h = hashlib.sha256(fingerprint.encode())
    for r in rows:
        h.update(f"|{r.nature}:{r.from_no}:{r.to_no}:{r.total}:{r.cancelled}:{r.source}:{int(r.counted)}".encode())
    return h.hexdigest()


def latest(tx, instance_id: uuid.UUID) -> Confirmation | None:
    head = tx.execute(
        text(
            "select id, version, build_fingerprint, created_at from filing.table13_confirmations"
            " where instance_id = :i order by version desc limit 1"
        ),
        {"i": instance_id},
    ).first()
    if head is None:
        return None
    rows = tx.execute(
        text(
            "select nature, from_no, to_no, total_count, cancelled_count, source, counted from filing.table13_rows"
            " where confirmation_id = :c order by row_no"
        ),
        {"c": head.id},
    )
    return Confirmation(head.id, head.version, head.build_fingerprint, head.created_at,
                        tuple(DocRow(r.nature, r.from_no, r.to_no, r.total_count, r.cancelled_count, r.source, r.counted)
                              for r in rows))  # fmt: skip


def current(tx, build: ReturnBuild) -> Confirmation | None:
    """The latest confirmation, only if it was made for this build as it is now."""
    c = latest(tx, build.instance.id)
    return c if c is not None and c.fingerprint == build.fingerprint else None


def counted_rows(tx, build: ReturnBuild) -> tuple[DocRow, ...]:
    """What the file and the snapshot carry: the counted rows of a confirmation that still stands; none otherwise."""
    c = current(tx, build)
    return () if c is None else tuple(r for r in c.rows if r.counted)


def working_rows(suggested: list[DocRow], last: Confirmation | None) -> list[DocRow]:
    """What the screen shows: each suggestion with the person's earlier edits laid over it, then their manual rows."""
    kept = {r.key: r for r in last.rows} if last else {}
    out = []
    for s in suggested:
        k = kept.get(s.key)
        out.append(s if k is None or k.source == "manual" else DocRow(s.nature, s.from_no, s.to_no, k.total, k.cancelled,
                                                                      s.source, k.counted, s.missing))  # fmt: skip
    keys = {r.key for r in out}
    out += [r for r in (last.rows if last else ()) if r.source == "manual" and r.key not in keys]
    return out


def confirm(uow: BusinessUoW, inst: ReturnInstance, build: ReturnBuild, sent: list[tuple[DocRow, bool]]) -> tuple[Confirmation, bool]:
    """Record the rows as the next version for this return. `sent` pairs each row with whether it is a manual row. A suggested
    row must be one of the suggestions of this build as it is now (from and to are never edited on one); the same
    confirmation again returns the version already written. Returns the confirmation and whether it is new."""
    if inst.form != "GSTR1":
        raise Conflict("table13_not_applicable", "Documents issued are filed with the monthly or quarterly GSTR-1 only.")
    if inst.status != "open":
        raise Conflict("return_not_open", "This return is not open, so its documents issued cannot be changed.")
    tx, p = uow.tx, uow.principal
    lock_instance(tx, inst.id)
    suggested = {s.key: s for s in suggest(build.lines, build.cancelled)}
    rows: list[DocRow] = []
    for r, manual in sent:
        if manual:
            rows.append(DocRow(r.nature, r.from_no, r.to_no, r.total, r.cancelled, "manual", r.counted))
            continue
        s = suggested.get(r.key)
        if s is None:
            raise Conflict("table13_not_current", "The suggested rows have changed. Reload the return and look at them again.")
        rows.append(DocRow(s.nature, s.from_no, s.to_no, r.total, r.cancelled, s.source, r.counted))
    try:
        validate(rows)
    except RowInvalid as exc:
        raise Invalid("table13_row_invalid", str(exc), field="rows") from exc
    digest = _hash(build.fingerprint, rows)
    prior = latest(tx, inst.id)
    if prior is not None and _hash(prior.fingerprint, list(prior.rows)) == digest:
        return prior, False
    version = (prior.version if prior else 0) + 1
    cid = uuid7()
    tx.execute(
        text("insert into filing.table13_confirmations (id, business_id, instance_id, version, build_fingerprint,"
             " created_by) values (:i, :b, :n, :v, :f, :u)"),
        {"i": cid, "b": p.business_id, "n": inst.id, "v": version, "f": build.fingerprint, "u": p.user_id},
    )  # fmt: skip
    if rows:
        tx.execute(
            text("insert into filing.table13_rows (confirmation_id, business_id, row_no, nature, from_no, to_no,"
                 " total_count, cancelled_count, source, counted) values (:c, :b, :n, :na, :f, :t, :tot, :can, :s, :ct)"),
            [{"c": cid, "b": p.business_id, "n": n, "na": r.nature, "f": r.from_no, "t": r.to_no, "tot": r.total,
              "can": r.cancelled, "s": r.source, "ct": r.counted} for n, r in enumerate(rows, 1)],
        )  # fmt: skip
    audit.record(uow, "return.table13_confirmed", "return_instance", inst.id,
                 data={"version": version, "rows": len(rows), "counted": sum(r.counted for r in rows)})  # fmt: skip
    return latest(tx, inst.id), True  # type: ignore[return-value]
