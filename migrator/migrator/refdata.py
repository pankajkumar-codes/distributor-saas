"""Loads the reference data under refdata/ into the refdata schema (LLD-0 §6).

The migrator runs this after the SQL migrations, in its own transaction, on every
run. Files:

    refdata/values/*.yaml       scalar rules, one list of entries per file
    refdata/state_codes.yaml    GST state and UT codes
    refdata/templates/index.yaml   one entry per template file, checked by SHA-256

Rules (§6.3):
- Every file is validated first; one invalid entry fails the whole load, so the
  migrator run fails with it and nothing is written.
- A row is identified by (key, valid_from). Its value columns are never changed:
  editing one is refused. Only last_checked, status, source_url, source_title and
  note may change, and those updates are counted in refdata.loads.
- A new value is a new entry with a later valid_from. The loader closes the earlier
  row by setting its valid_to to the new valid_from; that is the only change it
  makes to a value column, and only from null.
- A row in the database that the files no longer list is refused (rows are never
  deleted).
- Running the same files twice writes nothing but a refdata.loads row with zero
  counts, which also tells running containers to drop their cache.

Check files without a database (the CI `refdata` job):

    python -m migrator.refdata check refdata/
"""

import datetime as dt
import hashlib
import json
import os
import re
import sys
import uuid
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

import yaml

TYPES = ("integer", "decimal", "text", "boolean", "pattern", "enum")
KINDS = ("tax", "product")
STATUSES = {"product": ("provisional", "po_confirmed"), "tax": ("provisional", "expert_confirmed", "ca_confirmed")}
TAX_STATUSES = STATUSES["tax"]
KEY = re.compile(r"^[a-z0-9_]+(\.[a-z0-9_]+)+$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
# What may change on a loaded row (§6.3). valid_to is handled separately: null -> date only.
# confirmed_by / confirmed_on make a status change auditable: any status but provisional
# names who confirmed the row and when (D-038).
METADATA = ("source_url", "source_title", "last_checked", "status", "note", "confirmed_by", "confirmed_on")


class RefdataInvalid(Exception):
    """The files break a rule; the message lists every problem found."""

    def __init__(self, problems: list[str]):
        super().__init__("refdata is invalid:\n  " + "\n  ".join(problems))
        self.problems = problems


@dataclass
class Row:
    table: str  # values | state_codes
    ident: str  # key or code
    valid_from: dt.date
    valid_to: dt.date | None
    columns: dict  # value/type/kind or name: what never changes
    metadata: dict  # METADATA columns
    loaded_from: str


@dataclass
class Template:
    key: str
    version: str
    sha256: str
    file_name: str
    source_url: str
    last_checked: dt.date
    status: str
    confirmed_by: str | None = None
    confirmed_on: dt.date | None = None


@dataclass
class Files:
    rows: list[Row] = field(default_factory=list)
    templates: list[Template] = field(default_factory=list)
    hashes: dict[str, str] = field(default_factory=dict)  # relative path -> sha256


def _date(value, where, name, problems, required=True):
    if value is None:
        if required:
            problems.append(f"{where}: {name} is required")
        return None
    if isinstance(value, dt.datetime) or not isinstance(value, dt.date):
        problems.append(f"{where}: {name} must be a date (YYYY-MM-DD), got {value!r}")
        return None
    return value


def _text(entry, name, where, problems, required=True):
    value = entry.get(name)
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            problems.append(f"{where}: {name} is required")
        return None
    if not isinstance(value, str):
        problems.append(f"{where}: {name} must be a string, got {value!r}")
        return None
    return value


def _source_url(entry, where, problems):
    url = _text(entry, "source_url", where, problems)
    # A public source is an https link. A decision recorded only in the project's own
    # documents (the BRD, an LLD) is cited by its project path, e.g. team/docs/lld-1.md.
    if url and not (url.startswith("https://") or url.startswith("team/")):
        problems.append(f"{where}: source_url must be an https:// link or a team/ project path, got {url!r}")
    return url


def check_value(value: str, type_: str, allowed=None) -> str | None:
    """None if `value` reads as `type_`, else why not."""
    if type_ == "integer":
        return None if re.fullmatch(r"-?[0-9]+", value) else "not an integer"
    if type_ == "decimal":
        try:
            Decimal(value)
        except InvalidOperation:
            return "not a decimal"
        return None if re.fullmatch(r"-?[0-9]+(\.[0-9]+)?", value) else "not a plain decimal"
    if type_ == "boolean":
        return None if value in ("true", "false") else "boolean must be true or false"
    if type_ == "pattern":
        try:
            re.compile(value)
        except re.error as e:
            return f"pattern does not compile: {e}"
        return None
    if type_ == "enum":
        if not allowed or not isinstance(allowed, list) or not all(isinstance(a, str) for a in allowed):
            return "enum needs allowed: a list of strings"
        return None if value in allowed else f"{value!r} is not one of {allowed}"
    return None  # text


def _confirmation(entry, where, problems, status):
    """A confirmed row names who confirmed it and when; a provisional one names nobody."""
    by = entry.get("confirmed_by")
    on = _date(entry.get("confirmed_on"), where, "confirmed_on", problems, required=False)
    if status == "provisional":
        if by is not None or on is not None:
            problems.append(f"{where}: a provisional row has no confirmed_by / confirmed_on")
        return None, None
    if status is not None:
        if not isinstance(by, str) or not by.strip():
            problems.append(f"{where}: status {status} needs confirmed_by (who confirmed it, e.g. \"GST expert, RS-9\")")
        if on is None:
            problems.append(f"{where}: status {status} needs confirmed_on (the date it was confirmed)")
        elif on > dt.date.today():  # noqa: TID251 (a file check, not a business date)
            problems.append(f"{where}: confirmed_on {on} is in the future")
    return by, on


def _common(entry, where, problems, kind):
    valid_from = _date(entry.get("valid_from"), where, "valid_from", problems)
    valid_to = _date(entry.get("valid_to"), where, "valid_to", problems, required=False)
    if valid_from and valid_to and valid_to <= valid_from:
        problems.append(f"{where}: valid_to must be after valid_from")
    status = _text(entry, "status", where, problems)
    if status and kind in STATUSES and status not in STATUSES[kind]:
        problems.append(f"{where}: status {status!r} is not allowed for kind {kind} (allowed: {STATUSES[kind]})")
    note = entry.get("note")
    if note is not None and not isinstance(note, str):
        problems.append(f"{where}: note must be a string")
    confirmed_by, confirmed_on = _confirmation(entry, where, problems, status)
    metadata = {
        "confirmed_by": confirmed_by,
        "confirmed_on": confirmed_on,
        "source_url": _source_url(entry, where, problems),
        "source_title": _text(entry, "source_title", where, problems),
        "last_checked": _date(entry.get("last_checked"), where, "last_checked", problems),
        "status": status,
        "note": note,
    }
    return valid_from, valid_to, metadata


def _entries(path: Path, rel: str, problems) -> list:
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError as e:
        problems.append(f"{rel}: not valid YAML: {e}")
        return []
    if data is None:
        return []
    if not isinstance(data, list) or not all(isinstance(e, dict) for e in data):
        problems.append(f"{rel}: must be a list of mappings")
        return []
    return data


def _values_file(path: Path, rel: str, stamp: str, problems) -> list[Row]:
    rows = []
    allowed_keys = {"key", "value", "type", "allowed", "kind", "valid_from", "valid_to", *METADATA}
    for i, entry in enumerate(_entries(path, rel, problems), 1):
        where = f"{rel} entry {i}"
        unknown = sorted(set(entry) - allowed_keys)
        if unknown:
            problems.append(f"{where}: unknown fields {unknown}")
        key = _text(entry, "key", where, problems)
        if key and not KEY.match(key):
            problems.append(f"{where}: key {key!r} must be dotted lower-case words, e.g. auth.code_ttl_minutes")
        where = f"{rel} {key or f'entry {i}'}"
        value = entry.get("value")
        if not isinstance(value, str):
            problems.append(f"{where}: value must be a quoted string (type says how to read it), got {value!r}")
            value = None
        type_ = entry.get("type")
        if type_ not in TYPES:
            problems.append(f"{where}: type must be one of {TYPES}, got {type_!r}")
        elif value is not None and (why := check_value(value, type_, entry.get("allowed"))):
            problems.append(f"{where}: value {value!r}: {why}")
        if "allowed" in entry and type_ != "enum":
            problems.append(f"{where}: allowed is only for type enum")
        kind = entry.get("kind")
        if kind not in KINDS:
            problems.append(f"{where}: kind must be tax or product, got {kind!r}")
        valid_from, valid_to, metadata = _common(entry, where, problems, kind)
        if key and value is not None and valid_from:
            rows.append(
                Row("values", key, valid_from, valid_to, {"value": value, "type": type_, "kind": kind}, metadata,
                    f"{rel}@{stamp}")
            )
    return rows


def _state_codes_file(path: Path, rel: str, stamp: str, problems) -> list[Row]:
    rows = []
    allowed_keys = {"code", "name", "valid_from", "valid_to", *METADATA}
    for i, entry in enumerate(_entries(path, rel, problems), 1):
        where = f"{rel} entry {i}"
        unknown = sorted(set(entry) - allowed_keys)
        if unknown:
            problems.append(f"{where}: unknown fields {unknown}")
        code = entry.get("code")
        if not isinstance(code, str) or not re.fullmatch(r"[0-9]{2}", code):
            problems.append(f"{where}: code must be a quoted two-digit string, got {code!r}")
            code = None
        name = _text(entry, "name", where, problems)
        valid_from, valid_to, metadata = _common(entry, f"{rel} {code or i}", problems, "tax")
        if code and name and valid_from:
            rows.append(Row("state_codes", code, valid_from, valid_to, {"name": name}, metadata, f"{rel}@{stamp}"))
    return rows


def _templates(root: Path, problems, hashes) -> list[Template]:
    index = root / "templates" / "index.yaml"
    if not index.exists():
        return []
    out = []
    for i, entry in enumerate(_entries(index, "templates/index.yaml", problems), 1):
        where = f"templates/index.yaml entry {i}"
        names = {n: _text(entry, n, where, problems) for n in ("key", "version", "file", "sha256", "status")}
        source_url = _source_url(entry, where, problems)
        last_checked = _date(entry.get("last_checked"), where, "last_checked", problems)
        if names["status"] and names["status"] not in TAX_STATUSES:
            problems.append(f"{where}: status must be one of {TAX_STATUSES}")
        if names["sha256"] and not SHA256.match(names["sha256"]):
            problems.append(f"{where}: sha256 must be 64 lower-case hex characters")
        if names["file"]:
            f = root / "templates" / names["file"]
            if "/" in names["file"] or not f.is_file():
                problems.append(f"{where}: file {names['file']!r} is not in refdata/templates/")
            else:
                actual = hashlib.sha256(f.read_bytes()).hexdigest()
                hashes[f"templates/{names['file']}"] = actual
                if names["sha256"] and actual != names["sha256"]:
                    problems.append(f"{where}: {names['file']} has sha256 {actual}, index says {names['sha256']}")
        confirmed_by, confirmed_on = _confirmation(entry, where, problems, names["status"])
        if all(names.values()) and source_url and last_checked:
            out.append(Template(names["key"], names["version"], names["sha256"], names["file"], source_url,
                                last_checked, names["status"], confirmed_by, confirmed_on))
    return out


def _check_ranges(rows: list[Row], problems) -> None:
    """Per key: no duplicate valid_from, no overlap, and an open row only last."""
    by_ident: dict[tuple[str, str], list[Row]] = {}
    for r in rows:
        by_ident.setdefault((r.table, r.ident), []).append(r)
    for (table, ident), group in by_ident.items():
        group.sort(key=lambda r: r.valid_from)
        for a, b in zip(group, group[1:], strict=False):
            if a.valid_from == b.valid_from:
                problems.append(f"{table} {ident}: two entries from {a.valid_from}")
            elif a.valid_to is not None and a.valid_to > b.valid_from:
                problems.append(f"{table} {ident}: {a.valid_from}..{a.valid_to} overlaps the entry from {b.valid_from}")
            elif a.valid_to is not None and a.valid_to < b.valid_from:
                pass  # a gap: no row covers those dates, and value_on raises there
            # a.valid_to None with a later entry: the loader closes it at b.valid_from.


def read_files(root: Path, stamp: str = "local") -> Files:
    """Validates every file under `root`; raises RefdataInvalid listing all problems."""
    problems: list[str] = []
    files = Files()
    if not root.is_dir():
        raise RefdataInvalid([f"{root} is not a directory"])
    for path in sorted((root / "values").glob("*.yaml")):
        rel = f"values/{path.name}"
        files.hashes[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
        files.rows += _values_file(path, rel, stamp, problems)
    states = root / "state_codes.yaml"
    if states.exists():
        files.hashes["state_codes.yaml"] = hashlib.sha256(states.read_bytes()).hexdigest()
        files.rows += _state_codes_file(states, "state_codes.yaml", stamp, problems)
    files.templates = _templates(root, problems, files.hashes)
    _check_ranges(files.rows, problems)
    seen = set()
    for t in files.templates:
        if (t.key, t.version) in seen:
            problems.append(f"templates/index.yaml: {t.key} {t.version} listed twice")
        seen.add((t.key, t.version))
    if problems:
        raise RefdataInvalid(problems)
    return files


def _effective(rows: list[Row]) -> None:
    """An open row followed by a later one for the same key ends where that one starts."""
    by_ident: dict[tuple[str, str], list[Row]] = {}
    for r in rows:
        by_ident.setdefault((r.table, r.ident), []).append(r)
    for group in by_ident.values():
        group.sort(key=lambda r: r.valid_from)
        for a, b in zip(group, group[1:], strict=False):
            if a.valid_to is None:
                a.valid_to = b.valid_from


_ID_COLUMN = {"values": "key", "state_codes": "code"}
_FIXED = {"values": ("value", "type", "kind"), "state_codes": ("name",)}


def load(conn, root: Path, git_sha: str | None = None) -> dict:
    """Validates and loads `root` in one transaction on `conn` (autocommit or not).

    Returns the refdata.loads counts. Raises RefdataInvalid, and writes nothing,
    when the files are invalid or would change a loaded row's value.
    """
    git_sha = git_sha or os.environ.get("GIT_SHA") or "local"
    files = read_files(root, git_sha)
    _effective(files.rows)
    counts = {"rows_inserted": 0, "rows_closed": 0, "rows_updated": 0}
    problems: list[str] = []
    with conn.transaction():
        # One loader at a time: two concurrent migrator runs would otherwise both insert.
        conn.execute("select pg_advisory_xact_lock(hashtextextended('refdata.load', 0))")
        for table in ("values", "state_codes"):
            idc = _ID_COLUMN[table]
            fixed = _FIXED[table]
            cols = (idc, "valid_from", "valid_to", *fixed, *METADATA)
            existing = {
                (r[0], r[1]): dict(zip(cols, r, strict=True))
                for r in conn.execute(f"select {', '.join(cols)} from refdata.{table}")  # noqa: S608 (fixed names)
            }
            wanted = {(r.ident, r.valid_from): r for r in files.rows if r.table == table}
            for ident, valid_from in sorted(set(existing) - set(wanted)):
                problems.append(f"{table} {ident} from {valid_from}: loaded before but no longer in the files "
                                "(rows are never deleted; close it with a later entry instead)")
            for (ident, valid_from), row in sorted(wanted.items()):
                old = existing.get((ident, valid_from))
                if old is None:
                    continue
                for c in fixed:
                    if old[c] != row.columns[c]:
                        problems.append(f"{table} {ident} from {valid_from}: {c} changed from {old[c]!r} to "
                                        f"{row.columns[c]!r}; add an entry with a later valid_from instead")
                if old["valid_to"] != row.valid_to and old["valid_to"] is not None:
                    problems.append(f"{table} {ident} from {valid_from}: valid_to {old['valid_to']} can't change")
            if problems:
                continue
            for (ident, valid_from), row in sorted(wanted.items()):
                old = existing.get((ident, valid_from))
                if old is not None and old["valid_to"] is None and row.valid_to is not None:
                    conn.execute(
                        f"update refdata.{table} set valid_to = %s, loaded_from = %s "  # noqa: S608
                        f"where {idc} = %s and valid_from = %s",
                        (row.valid_to, row.loaded_from, ident, valid_from),
                    )
                    counts["rows_closed"] += 1
            for (ident, valid_from), row in sorted(wanted.items()):
                old = existing.get((ident, valid_from))
                if old is None:
                    names = (idc, "valid_from", "valid_to", *fixed, *METADATA, "loaded_from")
                    values = (ident, valid_from, row.valid_to, *(row.columns[c] for c in fixed),
                              *(row.metadata[c] for c in METADATA), row.loaded_from)
                    conn.execute(
                        f"insert into refdata.{table} ({', '.join(names)}) "  # noqa: S608
                        f"values ({', '.join(['%s'] * len(names))})",
                        values,
                    )
                    counts["rows_inserted"] += 1
                elif any(old[c] != row.metadata[c] for c in METADATA):
                    conn.execute(
                        f"update refdata.{table} set {', '.join(f'{c} = %s' for c in METADATA)}, "  # noqa: S608
                        f"loaded_from = %s where {idc} = %s and valid_from = %s",
                        (*(row.metadata[c] for c in METADATA), row.loaded_from, ident, valid_from),
                    )
                    counts["rows_updated"] += 1
        existing_t = {
            (k, v): (sha, st, url, lc, cb, co)
            for k, v, sha, st, url, lc, cb, co in conn.execute(
                "select key, version, sha256, status, source_url, last_checked, confirmed_by, confirmed_on"
                " from refdata.templates"
            )
        }
        wanted_t = {(t.key, t.version): t for t in files.templates}
        for k, v in sorted(set(existing_t) - set(wanted_t)):
            problems.append(f"templates {k} {v}: loaded before but no longer in templates/index.yaml")
        for (k, v), t in sorted(wanted_t.items()):
            old = existing_t.get((k, v))
            if old is None:
                conn.execute(
                    "insert into refdata.templates (key, version, sha256, file_name, source_url, last_checked, status,"
                    " confirmed_by, confirmed_on) values (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (t.key, t.version, t.sha256, t.file_name, t.source_url, t.last_checked, t.status, t.confirmed_by,
                     t.confirmed_on),
                )
                counts["rows_inserted"] += 1
            elif old[0] != t.sha256:
                problems.append(f"templates {k} {v}: sha256 changed; a changed file is a new version")
            elif old[1:] != (t.status, t.source_url, t.last_checked, t.confirmed_by, t.confirmed_on):
                conn.execute(
                    "update refdata.templates set status = %s, source_url = %s, last_checked = %s,"
                    " confirmed_by = %s, confirmed_on = %s where key = %s and version = %s",
                    (t.status, t.source_url, t.last_checked, t.confirmed_by, t.confirmed_on, k, v),
                )
                counts["rows_updated"] += 1
        if problems:
            raise RefdataInvalid(problems)  # rolls the transaction back
        conn.execute(
            "insert into refdata.loads (id, git_sha, files, rows_inserted, rows_closed, rows_updated) "
            "values (%s, %s, %s, %s, %s, %s)",
            (uuid.uuid4(), git_sha, json.dumps(files.hashes, sort_keys=True), counts["rows_inserted"],
             counts["rows_closed"], counts["rows_updated"]),
        )
    return counts


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[0] != "check":
        print(__doc__, file=sys.stderr)
        return 2
    try:
        files = read_files(Path(argv[1]))
    except RefdataInvalid as e:
        print(e, file=sys.stderr)
        return 1
    print(f"refdata ok: {len(files.rows)} rows, {len(files.templates)} templates, {len(files.hashes)} files")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
