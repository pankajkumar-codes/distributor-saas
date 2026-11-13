"""Mapping profiles: how one report layout maps onto our normalized fields.

A profile is data, not code, so a verified layout for a marketplace report can be
added (or a marketplace's column rename handled) without a deploy of parser logic.
Every rule a profile applies is stated in it: which headers to expect, how dates are
written, which columns form the de-duplication key. Nothing is inferred.

No marketplace profiles ship yet. They are added only from real, anonymized sample
reports (docs/OPEN_QUESTIONS.md question 2) and marked verified once checked
against them.
"""

import datetime as dt
import enum
import re
from dataclasses import dataclass, field
from decimal import Decimal

MARKETPLACES = {"amazon", "flipkart", "meesho"}
# mtr_b2c and mtr_b2b are Amazon's Merchant Tax Report files (R1-M4).
REPORT_TYPES = {"orders", "invoices", "returns", "settlements", "fees", "mtr_b2c", "mtr_b2b", "cashback"}
_NAME = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


class ProfileError(ValueError):
    pass


class FieldKind(enum.StrEnum):
    text = "text"
    integer = "integer"
    # Decimal amounts and quantities; never parsed through float.
    decimal = "decimal"
    date = "date"
    datetime = "datetime"


@dataclass(frozen=True)
class FieldSpec:
    name: str
    # Accepted header spellings, compared after trimming and case-folding.
    headers: tuple[str, ...]
    kind: FieldKind = FieldKind.text
    required: bool = True
    # strptime formats tried in order; required for date and datetime fields.
    formats: tuple[str, ...] = ()
    max_length: int = 500
    # Buyer name, address, phone or email: recognised so the header row is found and
    # the column is accounted for, but never stored, raw or normalized (LLD-7 L7-2).
    personal: bool = False
    # Decimal fields only: multiply the value by this after parsing (exact Decimal arithmetic), so a
    # file that writes a rate as a fraction (0.18) is stored as a percent (18.00) (platform-reader-spec
    # rule 3). The cell as written stays in the row's raw values.
    scale: Decimal | None = None
    # A de-duplication key field may be blank in some rows (a refund's credit note number is blank on a
    # sale); blank counts as "" in the key. Without this a key field must be required.
    key_blank_ok: bool = False
    # Cell texts (compared case-insensitively) that mean "nothing here", such as Meesho's literal `null`
    # in a date column; the field is then read as blank.
    blank_tokens: tuple[str, ...] = ()

    def __post_init__(self):
        if self.scale is not None and self.kind != FieldKind.decimal:
            raise ProfileError(f"field {self.name!r} has a scale but is not a decimal")
        if self.scale is not None and (not self.scale.is_finite() or self.scale <= 0):
            raise ProfileError(f"field {self.name!r} needs a positive scale")
        if not _NAME.match(self.name):
            raise ProfileError(f"invalid field name {self.name!r}")
        if not self.headers or any(not h.strip() for h in self.headers):
            raise ProfileError(f"field {self.name!r} needs at least one non-empty header")
        if self.kind in (FieldKind.date, FieldKind.datetime) and not self.formats:
            raise ProfileError(f"field {self.name!r} is a {self.kind} and must list its formats")
        if self.formats and self.kind not in (FieldKind.date, FieldKind.datetime):
            raise ProfileError(f"field {self.name!r} lists formats but is not a date")
        for fmt in self.formats:
            try:
                dt.datetime.now().strftime(fmt)
            except ValueError as exc:
                raise ProfileError(f"field {self.name!r} has a bad format {fmt!r}") from exc


@dataclass(frozen=True)
class MappingProfile:
    marketplace: str
    report_type: str
    version: str
    fields: tuple[FieldSpec, ...]
    # Fields whose values together identify one source record (for example the
    # marketplace order item ID). Must be stable external IDs, never name/date/amount.
    dedup_key: tuple[str, ...]
    # True only after the profile was checked against a real sample report.
    verified: bool = False
    # How many leading rows to search for the header row (reports often start with
    # a title or date-range line).
    header_search_rows: int = 10
    notes: str = ""
    # The name of a counter that is the last part of `dedup_key` and is not a column (Meesho has no row id,
    # so identical rows in one file are counted 1, 2, ...). Rows with the same other key parts but different
    # values are not numbered apart: they collide and are flagged `conflict`, never merged or dropped.
    occurrence_field: str | None = None
    by_name: dict[str, FieldSpec] = field(init=False, repr=False, compare=False)

    def __post_init__(self):
        if self.marketplace not in MARKETPLACES:
            raise ProfileError(f"unknown marketplace {self.marketplace!r}")
        if self.report_type not in REPORT_TYPES:
            raise ProfileError(f"unknown report type {self.report_type!r}")
        if not self.version.strip():
            raise ProfileError("profile needs a version")
        if not self.fields:
            raise ProfileError("profile needs at least one field")

        by_name: dict[str, FieldSpec] = {}
        seen_headers: dict[str, str] = {}
        for spec in self.fields:
            if spec.name in by_name:
                raise ProfileError(f"field {spec.name!r} is defined twice")
            by_name[spec.name] = spec
            for header in spec.headers:
                key = header_key(header)
                if key in seen_headers:
                    raise ProfileError(
                        f"header {header!r} is claimed by both {seen_headers[key]!r} and {spec.name!r}"
                    )
                seen_headers[key] = spec.name

        if not self.dedup_key:
            raise ProfileError("profile needs a de-duplication key")
        if self.occurrence_field is not None:
            if self.occurrence_field in by_name or self.dedup_key[-1] != self.occurrence_field:
                raise ProfileError("the occurrence counter must be the last part of the key and not a column")
        for name in self.dedup_key:
            if name == self.occurrence_field:
                continue
            if name not in by_name:
                raise ProfileError(f"de-duplication key field {name!r} is not defined")
            if not by_name[name].required and not by_name[name].key_blank_ok:
                raise ProfileError(f"de-duplication key field {name!r} must be required")
            if by_name[name].personal:
                raise ProfileError(f"de-duplication key field {name!r} cannot be personal")
        if not 1 <= self.header_search_rows <= 50:
            raise ProfileError("header_search_rows must be between 1 and 50")
        object.__setattr__(self, "by_name", by_name)

    @property
    def profile_id(self) -> str:
        return f"{self.marketplace}/{self.report_type}@{self.version}"

    @classmethod
    def from_dict(cls, data: dict) -> "MappingProfile":
        try:
            fields = tuple(
                FieldSpec(
                    name=f["name"],
                    headers=tuple(f["headers"]),
                    kind=FieldKind(f.get("kind", "text")),
                    required=bool(f.get("required", True)),
                    formats=tuple(f.get("formats", ())),
                    max_length=int(f.get("max_length", 500)),
                    personal=bool(f.get("personal", False)),
                    scale=Decimal(str(f["scale"])) if f.get("scale") is not None else None,
                    key_blank_ok=bool(f.get("key_blank_ok", False)),
                    blank_tokens=tuple(f.get("blank_tokens", ())),
                )
                for f in data["fields"]
            )
            return cls(
                marketplace=data["marketplace"],
                report_type=data["report_type"],
                version=str(data["version"]),
                fields=fields,
                dedup_key=tuple(data["dedup_key"]),
                verified=bool(data.get("verified", False)),
                header_search_rows=int(data.get("header_search_rows", 10)),
                notes=str(data.get("notes", "")),
                occurrence_field=data.get("occurrence_field"),
            )
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, ProfileError):
                raise
            raise ProfileError(f"invalid profile definition: {exc}") from exc


def header_key(header: str) -> str:
    return " ".join(header.split()).casefold()
