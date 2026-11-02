"""Product CSV import (LLD-3 §7), as plain functions over bytes in the caller's unit of
work. S3-c2 puts them behind the upload routes and the parse and apply jobs.

Nothing here guesses (CLAUDE.md rule 10): the template's columns are matched exactly, a
code that appears twice in a file holds every such row, an invalid row is never applied,
and a row whose product moved after the preview is reported stale, not overwritten. The
file is identified by its SHA-256: a file already applied is not applied again [RM43-5].
Every row checks with the same functions the product routes use, so the import can't
accept what the screen refuses.
"""

import csv
import io
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import bindparam, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.types import JSON

from app.modules.imports.interface import FileRejected, looks_like_formula, read_table
from app.modules.refdata import value_on
from platform_common import audit
from platform_common.errors import AppError, Conflict, Deny, Invalid
from platform_common.ids import uuid7
from platform_common.uow import UnitOfWork

from . import checks
from .rates import RateRow, check_rate, live, parse_rate, rate_on

TEMPLATE = ("code", "name", "hsn", "unit", "sale_rate", "gst_rate", "gst_rate_valid_from", "barcode",
            "tax_category", "has_cess")
REQUIRED = ("code", "name", "unit", "sale_rate", "gst_rate", "gst_rate_valid_from", "tax_category")
_YES, _NO = ("yes", "y", "true", "1"), ("", "no", "n", "false", "0")
_DATE_FORMATS = ("%d-%m-%Y", "%Y-%m-%d")
_BATCH = 500  # rows per insert


def template_csv() -> bytes:
    """The header row users fill in (§7.1), as UTF-8 CSV."""
    out = io.StringIO()
    csv.writer(out, lineterminator="\r\n").writerow(TEMPLATE)
    return out.getvalue().encode()


@dataclass(frozen=True)
class Run:
    id: uuid.UUID
    file_name: str
    s3_key: str
    sha256: str | None
    status: str
    counts: dict | None
    error_code: str | None
    error_message: str | None
    duplicate_of: uuid.UUID | None
    superseded_by: uuid.UUID | None
    apply_changes: bool | None
    created_at: datetime


_RUN_COLUMNS = ("id, file_name, s3_key, sha256, status, counts, error_code, error_message, duplicate_of,"
                " superseded_by, apply_changes, created_at")


def _business(uow: UnitOfWork) -> uuid.UUID:
    return uow.principal.business_id


def _me(uow: UnitOfWork) -> uuid.UUID:
    return uow.principal.user_id


def get_run(uow: UnitOfWork, run_id: uuid.UUID, *, lock: bool = False) -> Run:
    row = uow.tx.execute(
        text(f"select {_RUN_COLUMNS} from catalog.import_runs where id = :r and business_id = :b"
             + (" for update" if lock else "")),
        {"r": run_id, "b": _business(uow)},
    ).one_or_none()
    if row is None:
        raise Deny("not_found")  # unknown or another business's run
    return Run(*row)


def _set_run(uow: UnitOfWork, run_id: uuid.UUID, **cols) -> None:
    sets = ", ".join(f"{k} = :{k}" for k in cols)
    stmt = text(f"update catalog.import_runs set {sets}, updated_at = now(), version = version + 1"
                " where id = :r and business_id = :b")
    if "counts" in cols:
        stmt = stmt.bindparams(bindparam("counts", type_=JSON))
    uow.tx.execute(stmt, {**cols, "r": run_id, "b": _business(uow)})


def start(uow: UnitOfWork, file_name: str, size_bytes: int, today: date) -> Run:
    """A run waiting for its upload (§6.3). The object key is fixed by the run's ID."""
    name = (file_name or "").strip()
    if not name or len(name) > 255 or not name.isprintable():
        raise Invalid("file_name_invalid", "Give the file's name", field="file_name")
    most = int(value_on(uow.tx, "catalog.import.max_bytes", today))
    if isinstance(size_bytes, bool) or not isinstance(size_bytes, int) or not 0 < size_bytes <= most:
        raise Invalid("file_too_large", f"The file can be at most {most // 1024} KB", field="size_bytes")
    run_id = uuid7()
    uow.tx.execute(
        text("insert into catalog.import_runs (id, business_id, file_name, s3_key, size_bytes, created_by)"
             " values (:r, :b, :n, :k, :s, :me)"),
        {"r": run_id, "b": _business(uow), "n": name, "k": f"b/{_business(uow)}/catalog-imports/{run_id}",
         "s": size_bytes, "me": _me(uow)},
    )
    return get_run(uow, run_id)


def fail(uow: UnitOfWork, run_id: uuid.UUID, code: str, message: str) -> None:
    """For the jobs: a run that can't go on, with the reason shown to the user."""
    _set_run(uow, run_id, status="failed", error_code=code, error_message=message[:500])


# --- Parse -------------------------------------------------------------------------


@dataclass
class _Row:
    number: int
    cells: dict
    code_key: str | None = None
    fields: dict | None = None  # checked product fields
    rate: tuple[Decimal, date] | None = None
    errors: list | None = None
    status: str = "invalid"
    product_id: uuid.UUID | None = None
    compared_version: int | None = None
    diff: list | None = None


def _error(field: str, code: str, message: str) -> dict:
    return {"field": field, "code": code, "message": message}


def _date(raw: str) -> date:
    value = raw.strip().removesuffix(" 00:00:00")  # an Excel date cell reads as midnight
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise Invalid("date_invalid", "Write the date as DD-MM-YYYY or YYYY-MM-DD")


def _flag(raw: str) -> bool:
    value = raw.strip().lower()
    if value in _YES:
        return True
    if value in _NO:
        return False
    raise Invalid("has_cess_invalid", "Write yes or no")


def _check_row(uow: UnitOfWork, row: _Row, today: date) -> None:
    """§4's checks on one row. Fills row.fields and row.rate, or row.errors."""
    tx, cells, errors, fields = uow.tx, row.cells, [], {}
    for column, value in cells.items():
        if value and looks_like_formula(value):
            errors.append(_error(column, "formula", "This looks like a spreadsheet formula; type the value instead"))
    if errors:
        row.errors = errors
        return

    def take(column, fn):
        try:
            return fn(cells.get(column, ""))
        except AppError as exc:
            errors.append(_error(column, exc.code, exc.message))
            return None

    fields["code"] = take("code", lambda v: checks.code(tx, v, today))
    fields["name"] = take("name", checks.name)
    fields["hsn"] = take("hsn", lambda v: checks.hsn(tx, v, today))
    fields["uqc"] = take("unit", lambda v: checks.uqc(tx, v, today))
    fields["sale_rate"] = take("sale_rate", checks.sale_rate)
    fields["barcode"] = take("barcode", checks.barcode)
    fields["tax_category"] = take("tax_category", lambda v: checks.tax_category(v.strip().lower()))
    fields["has_cess"] = take("has_cess", _flag)
    raw_rate, raw_from = cells.get("gst_rate", "").strip(), cells.get("gst_rate_valid_from", "").strip()
    if fields["tax_category"] == "taxable":
        # The app never fills a rate (AC3-4): a taxable row without one is invalid.
        if not raw_rate or not raw_from:
            errors.append(_error("gst_rate", "rate_required",
                                 "A taxable product needs its GST rate and the date it applies from"))
        else:
            rate = take("gst_rate", parse_rate)
            valid_from = take("gst_rate_valid_from", _date)
            if rate is not None and valid_from is not None:
                try:
                    check_rate(tx, rate, valid_from, today)
                    row.rate = (rate, valid_from)
                except AppError as exc:
                    field = "gst_rate_valid_from" if exc.code == "valid_from_out_of_range" else "gst_rate"
                    errors.append(_error(field, exc.code, exc.message))
    elif fields["tax_category"] is not None and (raw_rate or raw_from):
        errors.append(_error("gst_rate", "rate_not_allowed", "Exempt, nil-rated and non-GST products have no GST rate"))
    row.fields, row.errors = fields, errors or None


def _existing(uow: UnitOfWork, keys: list[str]) -> tuple[dict, dict]:
    """Products not deleted whose code matches, by lower(code), and their rate rows."""
    if not keys:
        return {}, {}
    products = {
        r.code_key: r
        for r in uow.tx.execute(
            text(
                "select lower(code) as code_key, id, code, name, hsn, uqc, sale_rate, barcode, tax_category,"
                " has_cess, status, version from catalog.products"
                " where business_id = :b and status <> 'deleted' and lower(code) in :keys"
            ).bindparams(bindparam("keys", expanding=True)),
            {"b": _business(uow), "keys": keys},
        )
    }
    rates: dict = {p.id: [] for p in products.values()}
    if rates:
        for product_id, *rate in uow.tx.execute(
            text(
                "select r.product_id, r.id, r.rate, r.valid_from,"
                " exists (select 1 from catalog.product_rate_voids v where v.rate_id = r.id),"
                " coalesce((select c.action = 'confirm' from catalog.product_rate_confirmations c"
                "           where c.rate_id = r.id order by c.created_at desc, c.id desc limit 1), false)"
                " from catalog.product_rates r where r.business_id = :b and r.product_id in :ids"
            ).bindparams(bindparam("ids", expanding=True)),
            {"b": _business(uow), "ids": list(rates)},
        ):
            rates[product_id].append(RateRow(*rate))
    return products, rates


def _barcodes_taken(uow: UnitOfWork, barcodes: list[str]) -> dict:
    """lower(barcode) -> the active product holding it."""
    if not barcodes:
        return {}
    return dict(uow.tx.execute(
        text("select lower(barcode), id from catalog.products where business_id = :b and status = 'active'"
             " and lower(barcode) in :codes").bindparams(bindparam("codes", expanding=True)),
        {"b": _business(uow), "codes": barcodes},
    ).all())


def _text(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return f"{value.normalize():f}"  # 45.50 and 45.5 are the same price
    return str(value)


def _classify(uow: UnitOfWork, rows: list[_Row]) -> None:
    keys = {}
    for r in rows:
        code = (r.cells.get("code") or "").strip()
        if code:
            r.code_key = code.lower()
            keys.setdefault(r.code_key, []).append(r)
    # Detect, don't guess: every row of a code that repeats is held (§7.3).
    for same in keys.values():
        if len(same) > 1:
            numbers = ", ".join(str(r.number) for r in same)
            for r in same:
                r.status = "conflict"
                r.errors = [_error("code", "code_repeated", f"This code is on rows {numbers}; keep one")]
    barcode_rows: dict = {}
    for r in rows:
        if r.status != "conflict" and not r.errors and r.fields["barcode"]:
            barcode_rows.setdefault(r.fields["barcode"].lower(), []).append(r)
    for same in barcode_rows.values():
        if len(same) > 1:
            numbers = ", ".join(str(r.number) for r in same)
            for r in same:
                r.errors = [_error("barcode", "barcode_repeated", f"This barcode is on rows {numbers}")]
    products, rates = _existing(uow, [k for k, same in keys.items() if len(same) == 1])
    taken = _barcodes_taken(uow, list(barcode_rows))
    for r in rows:
        if r.status == "conflict":
            continue
        if r.errors:
            r.status = "invalid"
            continue
        p = products.get(r.code_key)
        holder = taken.get((r.fields["barcode"] or "").lower())
        if holder is not None and (p is None or holder != p.id):
            r.status, r.errors = "invalid", [_error("barcode", "barcode_taken",
                                                     "Another active product already uses this barcode")]
            continue
        if p is None:
            r.status = "new"
            continue
        _compare(r, p, rates[p.id])


def _compare(r: _Row, p, rate_rows: list[RateRow]) -> None:
    """changed or unchanged against product p; a new rate is a new row from the file's
    valid_from, never an edit of history (L3-1)."""
    if (r.fields["tax_category"] == "taxable") != (p.tax_category == "taxable"):
        r.status, r.errors = "invalid", [_error("tax_category", "tax_category_locked",
                                                 "A product can't move between taxable and not taxable")]
        return
    diff = [
        {"field": f, "saved": _text(getattr(p, f)), "file": _text(v)}
        for f, v in r.fields.items()
        if getattr(p, f) != v
    ]
    if p.status == "archived":
        diff.append({"field": "status", "saved": "archived", "file": "active"})
    if r.rate is not None:
        rate, valid_from = r.rate
        found = rate_on(rate_rows, valid_from, 0)
        if found is None or found.row.rate != rate:
            if any(x.valid_from == valid_from for x in live(rate_rows)):
                r.status, r.errors = "invalid", [_error(
                    "gst_rate_valid_from", "rate_exists_on_date",
                    f"This product already has a different rate from {valid_from:%d-%m-%Y}; void it first")]
                return
            diff.append({"field": "gst_rate", "saved": _text(found.row.rate) if found else None,
                         "file": f"{_text(rate)} from {valid_from.isoformat()}"})
    r.product_id, r.compared_version = p.id, p.version
    r.status, r.diff = ("changed", diff) if diff else ("unchanged", None)


def _parsed(r: _Row) -> dict:
    if r.fields is None or r.errors:
        return {k: v for k, v in r.cells.items() if v}  # as the file had it, for the preview
    out = {k: _text(v) if not isinstance(v, bool) else v for k, v in r.fields.items()}
    if r.rate is not None:
        out["gst_rate"], out["gst_rate_valid_from"] = _text(r.rate[0]), r.rate[1].isoformat()
    return out


def parse(uow: UnitOfWork, run_id: uuid.UUID, content: bytes, today: date) -> Run:
    """§7.3: the uploaded bytes to preview rows. A file the run can't use ends the run as
    failed (or discarded when it was already applied); the transaction still commits."""
    run = get_run(uow, run_id, lock=True)
    if run.status not in ("awaiting_upload", "parsing"):
        raise Conflict("import_not_parseable", "This upload has already been read")
    most = int(value_on(uow.tx, "catalog.import.max_bytes", today))
    if not content or len(content) > most:
        fail(uow, run_id, "file_too_large" if content else "file_empty",
             f"The file can be at most {most // 1024} KB" if content else "The file is empty")
        return get_run(uow, run_id)
    try:
        table = read_table(content, run.file_name)
    except FileRejected as exc:
        fail(uow, run_id, "file_rejected", str(exc))
        return get_run(uow, run_id)
    sha = table.checksum_sha256
    _set_run(uow, run_id, sha256=sha, size_bytes=len(content), status="parsing")

    # [RM43-5] The same file again: applied means nothing to do; an open preview is replaced.
    done = uow.tx.execute(
        text("select id from catalog.import_runs where business_id = :b and sha256 = :s"
             " and status in ('applying', 'applied') and id <> :r"),
        {"b": _business(uow), "s": sha, "r": run_id},
    ).scalar()
    if done is not None:
        _set_run(uow, run_id, status="discarded", duplicate_of=done, error_code="already_imported",
                 error_message="This file was already imported; nothing was added")
        return get_run(uow, run_id)
    for (old,) in uow.tx.execute(
        text("select id from catalog.import_runs where business_id = :b and sha256 = :s and status = 'preview'"
             " and id <> :r for update"),
        {"b": _business(uow), "s": sha, "r": run_id},
    ).all():
        _set_run(uow, old, status="discarded", superseded_by=run_id)
        audit.record(uow, "catalog.import_superseded", "product_import", old, data={"superseded_by": str(run_id)})

    if not table.rows:
        fail(uow, run_id, "header_missing", "The file has no header row")
        return get_run(uow, run_id)
    header = [h.strip().lower() for h in table.rows[0]]
    problem = _header_problem(header)
    if problem:
        fail(uow, run_id, "header_invalid", problem)
        return get_run(uow, run_id)
    data = [(i + 1, cells) for i, cells in enumerate(table.rows) if i > 0 and any(c.strip() for c in cells)]
    max_rows = int(value_on(uow.tx, "catalog.import.max_rows", today))
    if len(data) > max_rows:
        fail(uow, run_id, "too_many_rows", f"The file has {len(data)} products; the most in one file is {max_rows}")
        return get_run(uow, run_id)
    if not data:
        fail(uow, run_id, "no_rows", "The file has a header but no products")
        return get_run(uow, run_id)

    rows = []
    for number, cells in data:
        padded = list(cells) + [""] * (len(header) - len(cells))
        if len(padded) > len(header) and any(c.strip() for c in padded[len(header):]):
            r = _Row(number, {})
            r.errors = [_error("row", "extra_cells", "This row has more cells than the header")]
            rows.append(r)
            continue
        r = _Row(number, {h: v for h, v in zip(header, padded, strict=False)})
        _check_row(uow, r, today)
        rows.append(r)
    _classify(uow, rows)
    _insert_rows(uow, run_id, rows)
    counts = {s: sum(1 for r in rows if r.status == s) for s in ("new", "changed", "unchanged", "invalid", "conflict")}
    _set_run(uow, run_id, status="preview", counts=counts)
    return get_run(uow, run_id)


def _header_problem(header: list[str]) -> str | None:
    """Columns are matched exactly after trim and lower-case; no guessing (§7.1)."""
    seen = set()
    for h in header:
        if h in seen:
            return f"The column {h!r} appears twice"
        seen.add(h)
    unknown = [h for h in header if h not in TEMPLATE]
    if unknown:
        return f"Unknown column {unknown[0]!r}; use the template's columns: {', '.join(TEMPLATE)}"
    missing = [c for c in REQUIRED if c not in seen]
    if missing:
        return f"The column {missing[0]!r} is missing; use the template's columns: {', '.join(TEMPLATE)}"
    return None


def _insert_rows(uow: UnitOfWork, run_id: uuid.UUID, rows: list[_Row]) -> None:
    stmt = text(
        "insert into catalog.import_rows (id, business_id, run_id, row_number, code_key, parsed, status,"
        " product_id, compared_version, diff, errors)"
        " values (:id, :b, :run, :n, :key, :parsed, :status, :pid, :ver, :diff, :errors)"
    ).bindparams(bindparam("parsed", type_=JSON), bindparam("diff", type_=JSON), bindparam("errors", type_=JSON))
    for start_at in range(0, len(rows), _BATCH):
        uow.tx.execute(stmt, [
            {"id": uuid7(), "b": _business(uow), "run": run_id, "n": r.number, "key": r.code_key,
             "parsed": _parsed(r), "status": r.status, "pid": r.product_id, "ver": r.compared_version,
             "diff": r.diff, "errors": r.errors}
            for r in rows[start_at:start_at + _BATCH]
        ])


def rows(uow: UnitOfWork, run_id: uuid.UUID, status: str | None, limit: int, offset: int) -> tuple[list[dict], bool]:
    """The preview (§6.3): rows of one status, or all, in file order."""
    get_run(uow, run_id)
    where = "run_id = :r and business_id = :b" + (" and status = :s" if status else "")
    found = uow.tx.execute(
        text(f"select row_number, status, parsed, product_id, diff, errors, outcome from catalog.import_rows"
             f" where {where} order by row_number limit :limit offset :offset"),
        {"r": run_id, "b": _business(uow), "s": status, "limit": limit + 1, "offset": offset},
    ).mappings().all()
    return [dict(r) for r in found[:limit]], len(found) > limit


# --- Apply -------------------------------------------------------------------------


def apply(uow: UnitOfWork, run_id: uuid.UUID, apply_changes: bool) -> Run:
    """§7.4, in the caller's transaction: all or nothing. new rows become products with
    their first rate; changed rows apply when `apply_changes`; invalid and conflict rows
    never do. A row whose product moved after the preview is stale [RM43-6]."""
    run = get_run(uow, run_id, lock=True)  # a double confirm waits here, then sees applied
    if run.status == "applied":
        raise Conflict("import_already_applied", "This file has already been imported")
    if run.status != "preview":
        raise Conflict("import_not_ready", "This upload isn't ready to import")
    try:
        with uow.tx.begin_nested():
            _set_run(uow, run_id, status="applying")
    except IntegrityError:  # import_runs_live_checksum: the same file was applied meanwhile
        raise Conflict("import_already_applied", "This file has already been imported") from None
    outcome = {"applied": 0, "stale": 0, "skipped": 0}
    pending = uow.tx.execute(
        text("select id, row_number, code_key, parsed, status, product_id, compared_version, diff"
             " from catalog.import_rows where run_id = :r and business_id = :b and status in ('new', 'changed')"
             " order by row_number"),
        {"r": run_id, "b": _business(uow)},
    ).all()
    for row in pending:
        if row.status == "changed" and not apply_changes:
            result = "skipped"
        elif row.status == "new":
            result = _apply_new(uow, row)
        else:
            result = _apply_changed(uow, row)
        outcome[result] += 1
        uow.tx.execute(text("update catalog.import_rows set outcome = :o where id = :i and business_id = :b"),
                       {"o": result, "i": row.id, "b": _business(uow)})
    counts = {**(run.counts or {}), **outcome}
    _set_run(uow, run_id, status="applied", counts=counts, apply_changes=apply_changes, confirmed_by=_me(uow))
    uow.tx.execute(text("update catalog.import_runs set confirmed_at = now() where id = :r and business_id = :b"),
                   {"r": run_id, "b": _business(uow)})
    audit.record(uow, "catalog.import_applied", "product_import", run_id, data={"counts": counts})
    return get_run(uow, run_id)


def _insert_rate(uow: UnitOfWork, product_id: uuid.UUID, parsed: dict) -> None:
    """An imported rate is unconfirmed, whatever the file says (§7.4, BH-2)."""
    rate_id = uuid7()
    uow.tx.execute(
        text("insert into catalog.product_rates (id, business_id, product_id, rate, valid_from, source, created_by)"
             " values (:id, :b, :p, :r, :f, 'csv_import', :me)"),
        {"id": rate_id, "b": _business(uow), "p": product_id, "r": Decimal(parsed["gst_rate"]),
         "f": date.fromisoformat(parsed["gst_rate_valid_from"]), "me": _me(uow)},
    )
    audit.record(uow, "product.rate_added", "product", product_id,
                 data={"rate_id": str(rate_id), "rate": parsed["gst_rate"], "valid_from": parsed["gst_rate_valid_from"]})


_COLUMNS = ("code", "name", "hsn", "uqc", "sale_rate", "barcode", "tax_category", "has_cess")


def _values(parsed: dict) -> dict:
    out = {k: parsed.get(k) for k in _COLUMNS}
    out["sale_rate"] = Decimal(out["sale_rate"])
    return out


def _apply_new(uow: UnitOfWork, row) -> str:
    taken = uow.tx.execute(
        text("select id from catalog.products where business_id = :b and lower(code) = :k and status <> 'deleted'"
             " for update"),
        {"b": _business(uow), "k": row.code_key},
    ).first()
    if taken is not None:  # created by hand or by another import after the preview
        return "stale"
    product_id = uuid7()
    try:
        with uow.tx.begin_nested():
            uow.tx.execute(
                text(
                    "insert into catalog.products (id, business_id, code, name, hsn, uqc, sale_rate, barcode,"
                    " tax_category, has_cess, source_import_row_id, created_by, updated_by) values (:id, :b, :code,"
                    " :name, :hsn, :uqc, :sale_rate, :barcode, :tax_category, :has_cess, :row, :me, :me)"
                ),
                {"id": product_id, "b": _business(uow), "row": row.id, "me": _me(uow), **_values(row.parsed)},
            )
    except IntegrityError:  # a code or barcode taken in the moment since the check
        return "stale"
    audit.record(uow, "product.created", "product", product_id, data={"code": row.parsed["code"]})
    if row.parsed.get("gst_rate") is not None:
        _insert_rate(uow, product_id, row.parsed)
    return "applied"


def _apply_changed(uow: UnitOfWork, row) -> str:
    p = uow.tx.execute(
        text("select code, status, version from catalog.products where id = :p and business_id = :b for update"),
        {"p": row.product_id, "b": _business(uow)},
    ).one_or_none()
    if p is None or p.status == "deleted" or p.version != row.compared_version:
        return "stale"  # edited, archived, deleted or given a rate since the preview
    fields = {d["field"] for d in row.diff}
    values = _values(row.parsed)
    cols = {k: values[k] for k in _COLUMNS if k in fields}
    if "status" in fields:
        cols["status"] = "active"
    sets = "".join(f"{k} = :{k}, " for k in cols)
    try:
        with uow.tx.begin_nested():
            uow.tx.execute(
                text(f"update catalog.products set {sets}version = version + 1, updated_at = now(), updated_by = :me"
                     " where id = :p and business_id = :b"),
                {**cols, "me": _me(uow), "p": row.product_id, "b": _business(uow)},
            )
    except IntegrityError:  # a barcode taken since the preview
        return "stale"
    code = row.parsed["code"]
    if cols.keys() - {"status"}:
        audit.record(uow, "product.updated", "product", row.product_id,
                     data={"code": code, "fields": sorted(cols.keys() - {"status"})})
    if "status" in cols:
        audit.record(uow, "product.unarchived", "product", row.product_id, data={"code": code})
    if "gst_rate" in fields:
        _insert_rate(uow, row.product_id, row.parsed)
    return "applied"
