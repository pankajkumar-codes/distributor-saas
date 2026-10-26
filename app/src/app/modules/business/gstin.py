"""The GSTIN format check (LLD-1 §8.1, team/gst/gstin.md §1-2). Pure: no database.

It proves only that the string is well formed: never that the GSTIN is registered or
active (GC-P6), so nothing built on it may say "verified". Whether positions 1-2 name a
real state is reference data, checked by the caller against refdata.state_codes.
"""

import re
from dataclasses import dataclass, field

ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
SHAPE = re.compile(r"^[0-9]{2}[0-9A-Z]{10}[1-9A-Z][0-9A-Z][0-9A-Z]$")
PAN = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
TAN = re.compile(r"^[A-Z]{4}[0-9]{5}[A-Z]$")  # government TDS registrations (gstin.md §1)


@dataclass(frozen=True)
class GstinCheck:
    normalised: str
    ok: bool
    state_code: str | None
    errors: list[str] = field(default_factory=list)  # codes; MESSAGES has the words
    warnings: list[str] = field(default_factory=list)


MESSAGES = {
    "gstin_length": "GSTIN has {n} characters; it needs 15.",
    "gstin_shape": "GSTIN can only be digits and capital letters in the GSTIN pattern; please re-check the number.",
    "gstin_check_char": "GSTIN check character doesn't match; please re-check the number.",
    "gstin_state": "The first two digits of a GSTIN must be a state code.",
}


def normalise(value: str) -> str:
    return re.sub(r"\s+", "", value or "").upper()


def check_character(first14: str) -> str:
    """gstin.md §2: weights 1, 2, 1, 2, ... over the first 14 characters, mod 36."""
    total = 0
    for i, ch in enumerate(first14):
        v = ALPHABET.index(ch) * (2 if i % 2 else 1)
        total += v // 36 + v % 36
    return ALPHABET[(36 - total % 36) % 36]


def check_gstin(value: str, *, own: bool = True) -> GstinCheck:
    """`own` is a business's own GSTIN, which also warns if position 14 isn't Z (gstin.md
    §1); a supplier's or marketplace operator's may legitimately differ."""
    g = normalise(value)
    if len(g) != 15:
        return GstinCheck(g, False, None, ["gstin_length"])
    if not SHAPE.match(g):
        return GstinCheck(g, False, None, ["gstin_shape"])
    errors, warnings = [], []
    if check_character(g[:14]) != g[14]:
        errors.append("gstin_check_char")
    if not (PAN.match(g[2:12]) or TAN.match(g[2:12])):
        warnings.append("pan_shape")
    if own and g[13] != "Z":
        warnings.append("gstin_not_z")
    return GstinCheck(g, not errors, g[:2], errors, warnings)


def message(code: str, value: str = "") -> str:
    return MESSAGES[code].format(n=len(normalise(value)))
