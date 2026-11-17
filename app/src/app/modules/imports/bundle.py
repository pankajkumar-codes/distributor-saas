"""A bundle: one ZIP of mixed report files, opened safely and sorted by what each file holds (bundle plan, PR 1).

Two steps, both pure (no database, no object store, nothing logged from a cell):

1. `open_bundle` applies the guards. A failed guard is a safety matter, so it refuses the whole zip with one
   plain reason (`BundleRefused`). Folders are allowed; only each file's base name is used, and the path inside the
   zip is never kept. A zip inside the zip is opened once (`max_depth` 1); deeper is refused.
2. `classify` says what each file is, from its content, never from its name. A PDF by its first bytes. A workbook or
   CSV by its header row, asked of every registered reader (the same `detect` the single-file upload uses). Exactly
   one report matches, or the file is "not used" with a plain reason: nothing is guessed. A file whose report the
   business did not choose at setup is `not_selected`, listed and never read further.

It creates no rows, no tables and no uploads. Staging a classified bundle (one ordinary upload per used file) is a
later step that reuses the upload pipeline unchanged, so dedup, holds, review and confirm are not reimplemented here.
"""

import io
import stat
import unicodedata
import zipfile
import zlib
from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from app.modules.refdata import value_on

from .parsing import FileRejected, read_table, sheet_names
from .readers import SECTIONS, readers_for

PDF_MAGIC = b"%PDF-"
OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # an old .xls (or .doc): not read here
ZIP_MAGICS = (b"PK\x03\x04", b"PK\x05\x06")
JUNK_NAMES = {".ds_store", "thumbs.db", "desktop.ini"}

# What a person reads for each outcome. The code is stable; the words are product copy.
REASONS = {
    "empty": "This file is empty.",
    "too_large": "This file is too large.",
    "system_file": "Your computer added this file; it is not a report.",
    "old_excel": "This is an old Excel file (.xls). Save it as .xlsx and add it again.",
    "not_a_report": "This file type is not used.",
    "unreadable": "We could not read this file.",
    "no_match": "We could not tell which report this is.",
    "ambiguous": "This matches more than one report, so we did not guess.",
    "not_selected": "This report is not selected for your business.",
}
# Why the whole zip is refused (safety, not classification).
REFUSALS = {
    "not_a_zip": "This is not a readable zip file.",
    "empty_zip": "The zip has no files in it.",
    "too_many_files": "The zip holds too many files.",
    "too_big": "The zip expands to more than we can read.",
    "too_deep": "The zip has zips inside zips, nested too deep.",
    "unsafe_name": "The zip has a file with a path or name we do not accept.",
    "symlink": "The zip has a link in it, which we do not accept.",
    "encrypted": "The zip is password protected.",
    "duplicate_name": "The zip has two files with the same name. Rename one and zip again.",
    "damaged": "The zip has a damaged or unsupported file in it.",
}


class BundleRefused(ValueError):
    """The whole zip is refused. `code` is stable; `str()` is the plain reason."""

    def __init__(self, code: str):
        super().__init__(REFUSALS[code])
        self.code = code


@dataclass(frozen=True)
class Limits:
    max_files: int
    max_total_bytes: int  # everything inflated, all levels together
    max_file_bytes: int  # one file; a bigger one is listed as too large, not read
    max_depth: int  # 1: a zip inside the zip is opened; a zip inside that is refused


def limits_on(tx: Session, today: date) -> Limits:
    """The caps from refdata (`imports.bundle.*`, provisional product rows)."""
    return Limits(
        max_files=int(value_on(tx, "imports.bundle.max_files", today)),
        max_total_bytes=int(value_on(tx, "imports.bundle.max_total_bytes", today)),
        max_file_bytes=int(value_on(tx, "imports.bundle.max_file_bytes", today)),
        max_depth=int(value_on(tx, "imports.bundle.max_depth", today)),
    )


@dataclass(frozen=True)
class BundleFile:
    n: int  # position in the bundle, from 1, in archive order (a nested zip's files follow it in place)
    name: str  # the base name only
    data: bytes  # empty for a file over the per-file cap (not inflated)
    size: int  # its real size in bytes


@dataclass(frozen=True)
class Outcome:
    n: int
    name: str
    size: int
    section: str | None  # a section from `readers.SECTIONS`, or None
    state: str  # "used" | "not_used" | "not_selected"
    reason_code: str | None
    reason: str | None


def open_bundle(content: bytes, limits: Limits) -> list[BundleFile]:
    """The files of the zip, flat, in archive order. Raises BundleRefused when a guard fails."""
    files: list[BundleFile] = []
    seen: set[str] = set()
    budget = [limits.max_total_bytes]  # shared by every level, so a zip of zips cannot get round the cap
    _open(content, limits, 0, files, seen, budget)
    if not files:
        raise BundleRefused("empty_zip")
    return files


def _open(content: bytes, limits: Limits, depth: int, files: list[BundleFile], seen: set[str],
          budget: list[int]) -> None:
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise BundleRefused("not_a_zip") from exc
    for info in archive.infolist():
        if info.is_dir():
            continue
        if info.flag_bits & 0x1:
            raise BundleRefused("encrypted")
        if stat.S_ISLNK(info.external_attr >> 16):
            raise BundleRefused("symlink")
        base = _base_name(info.filename)
        if len(files) + 1 > limits.max_files:
            raise BundleRefused("too_many_files")
        if info.file_size > limits.max_file_bytes:
            # Listed as too large and never inflated. The declared size is only trusted to say "too big": a file that
            # claims to be small and inflates past the cap is stopped by `_inflate`.
            _add(files, seen, base, b"", info.file_size)
            continue
        data = _inflate(archive, info, min(limits.max_file_bytes, budget[0]))
        budget[0] -= len(data)
        if _is_nested_zip(data):
            if depth + 1 > limits.max_depth:
                raise BundleRefused("too_deep")
            _open(data, limits, depth + 1, files, seen, budget)
            continue
        _add(files, seen, base, data, len(data))


def _add(files: list[BundleFile], seen: set[str], name: str, data: bytes, size: int) -> None:
    key = unicodedata.normalize("NFC", name).casefold()
    if key in seen:
        raise BundleRefused("duplicate_name")
    seen.add(key)
    files.append(BundleFile(n=len(files) + 1, name=name, data=data, size=size))


def _base_name(raw: str) -> str:
    """The last part of an entry's path. A path that climbs out (`..`), starts at a root or a drive, or holds a
    control character is refused; the folders a person zipped are fine and are dropped."""
    path = raw.replace("\\", "/")
    parts = path.split("/")
    if path.startswith("/") or (len(path) > 1 and path[1] == ":") or ".." in parts or not path.isprintable():
        raise BundleRefused("unsafe_name")
    base = parts[-1].strip()
    if not base:
        raise BundleRefused("unsafe_name")
    return base


def _inflate(archive: zipfile.ZipFile, info: zipfile.ZipInfo, cap: int) -> bytes:
    """The entry's bytes, read with a hard cap that counts what actually comes out, so a small archive that
    expands enormously is stopped part-way."""
    if cap < 0:
        raise BundleRefused("too_big")
    try:
        with archive.open(info) as handle:
            data = handle.read(cap + 1)
    except (zipfile.BadZipFile, zlib.error, EOFError, NotImplementedError, RuntimeError) as exc:
        raise BundleRefused("damaged") from exc
    if len(data) > cap:
        # An entry that declared a size within the cap and inflated past it lied about its size: a bomb.
        raise BundleRefused("too_big")
    return data


def _is_nested_zip(data: bytes) -> bool:
    """A zip that is not an Office file. An .xlsx (or .docx) is a zip too; it carries `[Content_Types].xml`."""
    if not data.startswith(ZIP_MAGICS):
        return False
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as inner:
            return "[Content_Types].xml" not in inner.namelist()
    except zipfile.BadZipFile:
        return False


def _is_xlsx(data: bytes) -> bool:
    if not data.startswith(ZIP_MAGICS):
        return False
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as inner:
            return "xl/workbook.xml" in inner.namelist()
    except zipfile.BadZipFile:
        return False


def classify(files: list[BundleFile], *, selected: frozenset[str] | None = None) -> list[Outcome]:
    """What each file is. `selected` is the sections the business chose (None: every section is selected).
    Never raises for a bad file: a file that cannot be used is listed with its reason."""
    return [_classify_one(f, selected) for f in files]


def _out(f: BundleFile, section: str | None, state: str, code: str | None) -> Outcome:
    return Outcome(f.n, f.name, f.size, section, state, code, REASONS[code] if code else None)


def _classify_one(f: BundleFile, selected: frozenset[str] | None) -> Outcome:
    if f.size == 0:
        return _out(f, None, "not_used", "empty")
    if not f.data:  # over the per-file cap: never inflated
        return _out(f, None, "not_used", "too_large")
    if f.name.casefold() in JUNK_NAMES or f.name.startswith("._") or f.name.startswith("~$"):
        return _out(f, None, "not_used", "system_file")
    section, code = _section_of(f.data)
    if section is None:
        return _out(f, None, "not_used", code)
    if selected is not None and section not in selected:
        return _out(f, section, "not_selected", "not_selected")
    return _out(f, section, "used", None)


def _section_of(data: bytes) -> tuple[str | None, str | None]:
    """(section, None) when exactly one report matches the content, else (None, reason code)."""
    if data.startswith(PDF_MAGIC):
        return "own_invoices_pdf", None
    if data.startswith(OLE_MAGIC):
        return None, "old_excel"
    xlsx = _is_xlsx(data)
    if data.startswith(ZIP_MAGICS) and not xlsx:
        return None, "not_a_report"  # another Office file or a zip we did not open
    if not xlsx and (b"\x00" in data[:4096]):
        return None, "not_a_report"  # binary: an image or anything else
    readers = [r for s in SECTIONS if s != "own_invoices_pdf" for r in readers_for(s)]
    try:
        tables = _tables(data, readers, xlsx)
    except FileRejected:
        return None, "unreadable"
    if tables is None:
        return None, "no_match"
    sections = {r.section for t in tables for r in readers if _sheet_ok(r, t) and r.detect(t)}
    if not sections:
        return None, "no_match"
    if len(sections) > 1:
        return None, "ambiguous"
    return next(iter(sections)), None


def _tables(data: bytes, readers: list, xlsx: bool):
    """The tables to ask the readers about. A workbook is read sheet by sheet, only the sheets some reader names (a
    Help sheet is not read); one with a single sheet is read whatever it is called; several unnamed sheets give
    None (nothing to go on). Text is read as a CSV, under a made-up name: the real name is never consulted."""
    if not xlsx:
        return [read_table(data, "content.csv")]
    names = sheet_names(data)
    wanted = [s for s in names if any(_same(getattr(r, "sheet", None), s) for r in readers)]
    if wanted:
        return [read_table(data, "content.xlsx", sheet=s) for s in wanted]
    if len(names) == 1:
        return [read_table(data, "content.xlsx", sheet=names[0])]
    return None


def _same(a: str | None, b: str | None) -> bool:
    return a is not None and b is not None and a.strip().lower() == b.strip().lower()


def _sheet_ok(reader, table) -> bool:
    """The reading step's own rule for a reader's sheet (reading._sheet_ok), kept in step by a test."""
    wanted = getattr(reader, "sheet", None)
    return wanted is None or _same(wanted, table.sheet) or bool(getattr(reader, "any_sheet", False))


__all__ = ["BundleFile", "BundleRefused", "Limits", "Outcome", "REASONS", "REFUSALS", "classify", "limits_on",
           "open_bundle"]
