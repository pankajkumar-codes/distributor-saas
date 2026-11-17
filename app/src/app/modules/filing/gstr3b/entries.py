"""What the seller types into a GSTR-3B worksheet (Tables 3.1(d), 4, 5 and 5.1) and the checks on it (BRD GF-24).

Nothing here is computed from the invoices and nothing is checked against a rule of the GST law: the app only keeps what was
typed, refuses what cannot be an amount, and mirrors the offline utility (central tax typed once, state/UT tax equal to it).
Money is Decimal text with two decimals, never a float. Field names are `<table>.<row>.<head>`.
"""

import re
from decimal import Decimal

from .labels import TABLE_3_1, TABLE_4_AVAILABLE, TABLE_4_OTHER, TABLE_4_REVERSED, TABLE_5, TABLE_5_1, Row

TABLES: dict[str, tuple[Row, ...]] = {
    "t3_1": tuple(r for r in TABLE_3_1 if r.heads),
    "t4a": TABLE_4_AVAILABLE,
    "t4b": TABLE_4_REVERSED,
    "t4d": TABLE_4_OTHER,
    "t5": TABLE_5,
    "t5_1": TABLE_5_1,
}
FIELDS: frozenset[str] = frozenset(f"{t}.{r.key}.{h}" for t, rows in TABLES.items() for r in rows for h in r.heads)
_COPY_ROWS = {f"{t}.{r.key}" for t, rows in TABLES.items() for r in rows if r.sgst_copies_cgst}
_AMOUNT = re.compile(r"^[0-9]{1,13}(\.[0-9]{1,2})?$")
_CENT = Decimal("0.01")


class EntryError(ValueError):
    def __init__(self, field: str, message: str):
        super().__init__(message)
        self.field = field
        self.message = message


def _one(field: str, raw) -> str | None:
    if raw is None or (isinstance(raw, str) and raw.strip() == ""):
        return None
    if isinstance(raw, bool) or not isinstance(raw, (str, int)):  # a float is never an amount here
        raise EntryError(field, "Type the amount in rupees, for example 1250.50.")
    text = str(raw).strip().replace(",", "")
    if text.startswith("-"):
        raise EntryError(field, "An amount cannot be negative.")
    if not _AMOUNT.match(text):
        raise EntryError(field, "Type the amount in rupees with at most two decimals, for example 1250.50.")
    return str(Decimal(text).quantize(_CENT))


def normalize(raw: dict) -> dict[str, str]:
    """The cleaned entries: only typed fields, each as a two-decimal rupee string. Raises EntryError on the first bad field."""
    unknown = sorted(k for k in raw if k not in FIELDS)
    if unknown:
        raise EntryError(unknown[0], "That field is not part of the worksheet.")
    out: dict[str, str] = {}
    for field in sorted(raw):
        v = _one(field, raw[field])
        if v is not None:
            out[field] = v
    for row in _COPY_ROWS:  # central tax typed once; the state/UT column takes the same value (utility behaviour)
        c, s = out.get(f"{row}.cgst"), out.get(f"{row}.sgst")
        if s is not None and c is None:
            raise EntryError(f"{row}.sgst", "Type the central tax; the state/UT tax is the same amount.")
        if c is not None and s is not None and Decimal(c) != Decimal(s):
            raise EntryError(f"{row}.sgst", "Central tax and state/UT tax must be the same amount.")
        if c is not None and s is None:
            out[f"{row}.sgst"] = c
    return dict(sorted(out.items()))


def net_itc(entries: dict[str, str]) -> dict[str, str]:
    """Table 4 (C): the typed available ITC minus the typed reversed ITC, by head. Shown only; never checked or used."""
    out = {}
    for head in ("igst", "cgst", "sgst", "cess"):
        a = sum((Decimal(v) for k, v in entries.items() if k.startswith("t4a.") and k.endswith("." + head)), Decimal())
        b = sum((Decimal(v) for k, v in entries.items() if k.startswith("t4b.") and k.endswith("." + head)), Decimal())
        out[head] = str((a - b).quantize(_CENT))
    return out
