"""Number series settings (LLD-1 §4, business.series_settings): each document kind's
prefix, width and first value, and whether the business still issues practice documents
(BH-5). Sales copies a kind's settings into its own series row at the FY's first
finalize (LLD-4 L4-2)."""

import re
from dataclasses import dataclass
from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session

from platform_common import audit
from platform_common.errors import Invalid

from .frequency import BOUND


@dataclass(frozen=True)
class SeriesSetting:
    kind: str
    prefix: str
    width: int
    first_value: int
    practice_mode: bool


def series_setting(tx: Session, kind: str) -> SeriesSetting | None:
    """The bound business's settings for `kind`, or None when it has none yet (which
    finalize treats as practice mode, BH-5's default)."""
    row = tx.execute(
        text(
            f"select kind, prefix, width, first_value, practice_mode from business.series_settings"
            f" where {BOUND} and kind = :k"
        ),
        {"k": kind},
    ).one_or_none()
    return None if row is None else SeriesSetting(*row)


# --- The numbering settings screen (#461) ----------------------------------------------------------------------------
#
# Pankaj's format (D-114): <prefix>/YY-MM/NNNNNN, a series per month of the document's date that restarts at 1, so the
# width is fixed at 6 digits and the prefix is what the seller picks. Each kind is its own series (Rule 53(1A)(c)).
# Saving changes the prefix and first number only: practice_mode (live numbering) is not switched here.

KINDS = ("invoice", "credit_note", "debit_note")
DEFAULT_PREFIX = {"invoice": "INV", "credit_note": "CN", "debit_note": "DN"}
WIDTH = 6  # D-114: NNNNNN
_PREFIX = re.compile(r"^[A-Z0-9]+$")


def monthly_prefix(prefix: str, on: date) -> str:
    """INV and a document dated in November 2026 -> "INV/26-11/"."""
    return f"{prefix}/{on.year % 100:02d}-{on.month:02d}/"


def number_preview(prefix: str, width: int, value: int, scope: str, on: date) -> str:
    """The number `value` would get on `on`: INV/26-11/000001 under the monthly scope, INV000001 under the FY one."""
    head = monthly_prefix(prefix, on) if scope == "gstin_kind_month" else prefix
    return f"{head}{value:0{width}d}"


def max_prefix_length(width: int, scope: str, max_length: int) -> int:
    """The longest prefix whose every number fits Rule 46(b)'s limit: 16 - len("/YY-MM/") - 6 = 3 under D-114."""
    return max_length - (len(monthly_prefix("", date.min)) if scope == "gstin_kind_month" else 0) - width


@dataclass(frozen=True)
class Numbering:
    settings: tuple[SeriesSetting, ...]  # one per KINDS entry, saved or the default
    saved: frozenset[str]  # kinds with a saved row


def default_series_setting(kind: str) -> SeriesSetting:
    """The settings a kind has before any are saved: its default prefix, D-114's width, starting at 1, practice."""
    return SeriesSetting(kind, DEFAULT_PREFIX[kind], WIDTH, 1, True)


def numbering(tx: Session) -> Numbering:
    rows = {r.kind: SeriesSetting(*r) for r in tx.execute(text(
        f"select kind, prefix, width, first_value, practice_mode from business.series_settings where {BOUND}"))}
    out = tuple(rows.get(k) or default_series_setting(k) for k in KINDS)
    return Numbering(out, frozenset(rows))


def set_numbering(uow, sent: dict[str, dict], *, scope: str, max_length: int) -> Numbering:
    """Saves each kind's prefix and first number, or raises Invalid naming the first field at fault. Every number the
    saved prefix makes must fit `max_length` characters; two kinds may not share a prefix (one number would then stand
    for two documents). A prefix change applies to series started after it: a series already started keeps the prefix
    it began with (L4-2)."""
    tx, p = uow.tx, uow.principal
    longest = max_prefix_length(WIDTH, scope, max_length)
    current = {s.kind: s for s in numbering(tx).settings}
    clean: dict[str, tuple[str, int]] = {}
    for kind in KINDS:
        got = sent.get(kind)
        if got is None:
            clean[kind] = (current[kind].prefix, current[kind].first_value)
            continue
        prefix = (got.get("prefix") or "").strip().upper()
        if not _PREFIX.fullmatch(prefix):
            raise Invalid("prefix_invalid", "Use letters and digits only, like INV", field=f"{kind}.prefix")
        if len(prefix) > longest:
            raise Invalid("prefix_too_long",
                          f"Use at most {longest} letters: GST allows {max_length} characters in a number",
                          field=f"{kind}.prefix")
        first = got.get("first_number", 1)
        if not isinstance(first, int) or isinstance(first, bool) or not 1 <= first < 10**WIDTH:
            raise Invalid("first_number_invalid", f"Enter a number from 1 to {10**WIDTH - 1}", field=f"{kind}.first_number")
        clean[kind] = (prefix, first)
    seen: dict[str, str] = {}
    for kind in KINDS:
        prefix = clean[kind][0]
        if prefix in seen:
            raise Invalid("prefix_shared", "Each document type needs its own prefix", field=f"{kind}.prefix")
        seen[prefix] = kind
    for kind in KINDS:
        prefix, first = clean[kind]
        tx.execute(
            text("insert into business.series_settings (business_id, kind, prefix, width, first_value, updated_by)"
                 " values (:b, :k, :p, :w, :f, :by) on conflict (business_id, kind) do update"
                 " set prefix = excluded.prefix, width = excluded.width, first_value = excluded.first_value,"
                 " updated_at = now(), updated_by = excluded.updated_by"
                 " where (business.series_settings.prefix, business.series_settings.width,"
                 " business.series_settings.first_value) is distinct from"
                 " (excluded.prefix, excluded.width, excluded.first_value)"),
            {"b": p.business_id, "k": kind, "p": prefix, "w": WIDTH, "f": first, "by": p.user_id},
        )
    audit.record(uow, "business.numbering_update", "business", p.business_id,
                 data={"prefixes": {k: {"prefix": v[0], "first_value": v[1]} for k, v in clean.items()}})
    return numbering(tx)
