"""CSV exports that spreadsheet programs cannot execute (Global AC 6, SECURITY.md).

A text cell starting with =, +, -, @, tab or carriage return can be run as a formula
by Excel, LibreOffice or Google Sheets. Such cells are prefixed with a single quote
so they display as text. Numbers (int, Decimal) are written as numbers, so a
negative amount stays a negative amount. Floats are refused, as everywhere money is
involved.
"""

import csv
import io
from collections.abc import Iterable, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any

_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        raise TypeError("floats are not allowed in exports; use Decimal")
    if isinstance(value, int | Decimal):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    text = str(value)
    if text.startswith(_FORMULA_START):
        return "'" + text
    return text


def to_csv(header: Sequence[str], rows: Iterable[Sequence[Any]]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow([safe_cell(h) for h in header])
    for row in rows:
        if len(row) != len(header):
            raise ValueError(f"row has {len(row)} cells, header has {len(header)}")
        writer.writerow([safe_cell(v) for v in row])
    return buf.getvalue()
