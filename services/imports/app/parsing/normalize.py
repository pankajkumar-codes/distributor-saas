"""Applies a mapping profile to a source table, row by row.

One bad row never stops or alters the others: it is marked invalid with its errors
and the rest carry on. Rows sharing a de-duplication key are flagged, not merged:
identical copies become `duplicate`, differing ones all become `conflict` for a
person to review (BUSINESS_RULES.md section 2).
"""

import datetime as dt
import enum
import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from .files import FileRejected, SourceTable
from .profiles import FieldKind, FieldSpec, MappingProfile, header_key

# Plain or comma-grouped (Indian 1,23,456 or western 123,456), optional sign and fraction.
# re.ASCII: \d must not accept other scripts' digits (e.g. Arabic-Indic) as numbers.
_DECIMAL = re.compile(r"^[+-]?(\d+|\d{1,3}(,\d{2})*,\d{3}|\d{1,3}(,\d{3})+)(\.\d+)?$", re.ASCII)
_INTEGER = re.compile(r"^[+-]?\d+$", re.ASCII)
_CURRENCY_PREFIX = re.compile(r"^(₹|rs\.?|inr)\s*", re.IGNORECASE)
# Characters a spreadsheet treats as the start of a formula. A leading + or - is only
# allowed in number fields, where the strict patterns above reject anything else.
_FORMULA_PREFIXES = ("=", "@", "+", "-")


class HeaderMismatch(FileRejected):
    def __init__(self, message: str, missing_fields: list[str]):
        super().__init__(message)
        self.missing_fields = missing_fields


class RowStatus(enum.StrEnum):
    valid = "valid"
    invalid = "invalid"
    duplicate = "duplicate"
    conflict = "conflict"


@dataclass
class RowError:
    field: str | None
    code: str
    message: str


@dataclass
class ParsedRow:
    row_number: int
    # Every source column, keyed by its header as written in the file.
    raw: dict[str, str]
    normalized: dict[str, object] | None
    errors: list[RowError] = field(default_factory=list)
    status: RowStatus = RowStatus.valid
    dedup_key: tuple[str, ...] | None = None
    # Hash of the normalized values; lets a later import tell "same row again" from
    # "same external ID, changed content".
    content_hash: str | None = None
    # For duplicate/conflict rows: the row numbers sharing this key.
    related_rows: list[int] = field(default_factory=list)


@dataclass
class ParseResult:
    profile_id: str
    profile_verified: bool
    filename: str
    checksum_sha256: str
    sheet: str | None
    header_row_number: int
    headers: list[str]
    unmapped_headers: list[str]
    rows: list[ParsedRow]
    skipped_blank_rows: int

    def summary(self) -> dict[str, int]:
        counts = {status.value: 0 for status in RowStatus}
        for row in self.rows:
            counts[row.status.value] += 1
        counts["total"] = len(self.rows)
        counts["skipped_blank"] = self.skipped_blank_rows
        return counts


def parse(table: SourceTable, profile: MappingProfile) -> ParseResult:
    header_index, headers, columns = _locate_header(table, profile)

    labels = _raw_labels(headers)
    rows: list[ParsedRow] = []
    skipped = 0
    for offset, cells in enumerate(table.rows[header_index + 1 :], start=header_index + 2):
        if not any(c.strip() for c in cells):
            skipped += 1
            continue
        rows.append(_parse_row(offset, cells, labels, columns, profile))

    _flag_duplicates(rows)

    mapped = set(columns.values())
    return ParseResult(
        profile_id=profile.profile_id,
        profile_verified=profile.verified,
        filename=table.filename,
        checksum_sha256=table.checksum_sha256,
        sheet=table.sheet,
        header_row_number=header_index + 1,
        headers=headers,
        unmapped_headers=[h for i, h in enumerate(headers) if i not in mapped and h.strip()],
        rows=rows,
        skipped_blank_rows=skipped,
    )


def _locate_header(table: SourceTable, profile: MappingProfile):
    best_missing: list[str] | None = None
    for index, row in enumerate(table.rows[: profile.header_search_rows]):
        positions: dict[str, list[int]] = {}
        for col, header in enumerate(row):
            positions.setdefault(header_key(header), []).append(col)

        columns: dict[str, int] = {}
        missing: list[str] = []
        for spec in profile.fields:
            found = sorted({c for h in spec.headers for c in positions.get(header_key(h), [])})
            if len(found) > 1:
                names = ", ".join(repr(row[c]) for c in found)
                raise FileRejected(
                    f"row {index + 1} has more than one column for {spec.name!r} ({names}); "
                    "remove the extra column or fix the profile"
                )
            if found:
                columns[spec.name] = found[0]
            elif spec.required:
                missing.append(spec.name)

        if not missing:
            return index, list(row), columns
        if columns and (best_missing is None or len(missing) < len(best_missing)):
            best_missing = missing

    if best_missing is None:
        raise HeaderMismatch(
            f"no header row for {profile.profile_id} found in the first "
            f"{profile.header_search_rows} rows; is this the right report?",
            [s.name for s in profile.fields if s.required],
        )
    raise HeaderMismatch(
        f"report is missing required columns for {profile.profile_id}: " + ", ".join(best_missing),
        best_missing,
    )


def _parse_row(row_number, cells, labels, columns, profile) -> ParsedRow:
    raw = {label: cells[i] if i < len(cells) else "" for i, label in enumerate(labels)}
    errors: list[RowError] = []

    extra = [c for c in cells[len(labels) :] if c.strip()]
    if extra:
        errors.append(RowError(None, "extra_cells", f"row has {len(extra)} value(s) beyond the header columns"))
        for i, value in enumerate(cells[len(labels) :], start=len(labels)):
            raw[f"column_{i + 1}"] = value

    normalized: dict[str, object] = {}
    for spec in profile.fields:
        col = columns.get(spec.name)
        value = cells[col] if col is not None and col < len(cells) else ""
        try:
            normalized[spec.name] = _convert(spec, value)
        except _FieldInvalid as exc:
            errors.append(RowError(spec.name, exc.code, exc.message))

    row = ParsedRow(row_number=row_number, raw=raw, normalized=None, errors=errors)
    if errors:
        row.status = RowStatus.invalid
        return row

    row.normalized = normalized
    row.dedup_key = tuple(_canonical(normalized[name]) for name in profile.dedup_key)
    row.content_hash = hashlib.sha256(
        json.dumps({k: _canonical(v) for k, v in normalized.items()}, sort_keys=True).encode()
    ).hexdigest()
    return row


def _raw_labels(headers: list[str]) -> list[str]:
    labels: list[str] = []
    for i, header in enumerate(headers):
        label = header.strip() or f"column_{i + 1}"
        # Two source columns can share a header; keep both values under distinct keys.
        labels.append(label if label not in labels else f"{label} (column {i + 1})")
    return labels


def _flag_duplicates(rows: list[ParsedRow]) -> None:
    groups: dict[tuple[str, ...], list[ParsedRow]] = {}
    for row in rows:
        if row.dedup_key is not None:
            groups.setdefault(row.dedup_key, []).append(row)

    for members in groups.values():
        if len(members) < 2:
            continue
        numbers = [m.row_number for m in members]
        if len({m.content_hash for m in members}) > 1:
            for m in members:
                m.status = RowStatus.conflict
                m.related_rows = [n for n in numbers if n != m.row_number]
                m.errors.append(
                    RowError(None, "conflicting_duplicate", "same key as other rows but different values")
                )
        else:
            # The first copy stays valid; later identical copies are dropped from the import.
            for m in members[1:]:
                m.status = RowStatus.duplicate
                m.related_rows = [numbers[0]]


class _FieldInvalid(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message


def _looks_like_formula(value: str, kind: FieldKind) -> bool:
    # Fold look-alikes (full-width ＝) and drop invisible format characters (zero-width
    # space) so they cannot hide a formula prefix.
    folded = "".join(c for c in unicodedata.normalize("NFKC", value) if unicodedata.category(c) != "Cf")
    if folded[:1] in ("\t", "\r"):
        return True
    head = folded.lstrip()[:1]
    if kind in (FieldKind.integer, FieldKind.decimal):
        return head in ("=", "@")
    return head in _FORMULA_PREFIXES


def _convert(spec: FieldSpec, value: str):
    if _looks_like_formula(value, spec.kind):
        # Spreadsheet formulas (or text that a spreadsheet would run as one) are never
        # evaluated or passed on; the user fixes the source file instead.
        raise _FieldInvalid("formula", f"{value[:40]!r} looks like a spreadsheet formula")

    text = value.strip()
    if not text:
        if spec.required:
            raise _FieldInvalid("required", "value is required")
        return None

    if spec.kind == FieldKind.text:
        if len(text) > spec.max_length:
            raise _FieldInvalid("too_long", f"longer than {spec.max_length} characters")
        return text

    if spec.kind == FieldKind.integer:
        if not _INTEGER.match(text):
            raise _FieldInvalid("not_integer", f"{value!r} is not a whole number")
        return int(text)

    if spec.kind == FieldKind.decimal:
        number = _CURRENCY_PREFIX.sub("", text)
        if not _DECIMAL.match(number):
            raise _FieldInvalid("not_decimal", f"{value!r} is not a plain decimal number")
        try:
            return Decimal(number.replace(",", ""))
        except InvalidOperation:  # pragma: no cover - the regex already guarantees validity
            raise _FieldInvalid("not_decimal", f"{value!r} is not a plain decimal number")

    # date / datetime: every listed format is tried so ambiguous values are caught.
    results = set()
    for fmt in spec.formats:
        try:
            parsed = dt.datetime.strptime(text, fmt)
        except ValueError:
            continue
        results.add(parsed.date() if spec.kind == FieldKind.date else parsed)
    if not results:
        raise _FieldInvalid("bad_date", f"{value!r} matches none of the formats {list(spec.formats)}")
    if len(results) > 1:
        raise _FieldInvalid("ambiguous_date", f"{value!r} reads as more than one date under this profile")
    return results.pop()


def _canonical(value) -> str:
    if value is None:
        return ""
    if isinstance(value, Decimal):
        # 10, 10.0 and 10.00 are the same amount.
        return format(value.normalize(), "f")
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    return str(value)
