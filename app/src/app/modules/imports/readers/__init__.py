"""Report readers: what turns one kind of uploaded file into candidate rows (R1-M3).

A reader is data (a mapping profile) plus small per-report transforms. The upload
pipeline finds the readers of a section, asks each whether a file is theirs, and hands
the winner's profile to the existing parser. M3 shipped the interface and the registry with
no readers; Amazon, Flipkart and Meesho (M4, `register_platform_readers`) and the own-invoice
Excel sheet (M5) register theirs. A reader whose refdata `imports.profile.<id>.verified` is not true is still used,
but every run it makes carries the "layout unchecked" warning (LLD-7 L7-13); nothing is confirmed into documents in M4.

A reader never touches the database or the object store. It reads by header name, uses
`Decimal` only, and drops personal columns before a row is returned (parsing's rule).
"""

from typing import Protocol

from ..models import StagedRowStatus
from ..parsing import MappingProfile, ParsedRow, SourceTable

# The sections a user uploads into. Every one is optional.
SECTIONS = ("amazon", "flipkart", "meesho", "own_invoices_excel", "own_invoices_pdf")
PLATFORM_SECTIONS = ("amazon", "flipkart", "meesho")

# Why a row is held (LLD-7 §3 step 5). A reader may only choose from these.
HOLD_REASONS = ("blank_hsn", "blank_uqc", "unknown_state", "unknown_txn_type", "blank_qty", "sanity",
                "cashback_adjustment", "price_adjustment", "missing_original", "number_format")


class Reader(Protocol):
    id: str  # e.g. "amazon_mtr_b2c_v1"; also the refdata key stem imports.profile.<id>
    section: str
    report_type: str  # coverage: which report this file is (e.g. "mtr_b2c")
    sheet: str | None  # an Excel reader's own sheet name (whole-name, case-insensitive); None for a file with one table

    def accepts(self, name: str) -> bool:
        """For a zip: is this entry one of this reader's files, by exact file name pattern."""

    def detect(self, table: SourceTable) -> bool:
        """Does this file carry the headers this reader requires?"""

    def profile(self) -> MappingProfile: ...

    def gstin(self, table: SourceTable) -> str | None:
        """The seller GSTIN the file states (its own header block or column), or None."""

    def classify(self, row: ParsedRow) -> "tuple[StagedRowStatus, str | None] | None":
        """The hold rule, for a row that parsed as valid: (held, reason) with a reason from
        HOLD_REASONS, (skipped_zero, None) for a zero-value cancel or replacement, or None.

        A reader that needs refdata to decide (the state list, a pattern) names the keys in an optional
        `refdata_keys` attribute; the upload pipeline then calls `classify(row, context)` with
        `context["states"]` (every state code and name, case-folded) and each key's value. The reader
        itself still never touches the database."""


_registry: dict[str, Reader] = {}


def register(reader: Reader) -> None:
    if reader.section not in SECTIONS:
        raise ValueError(f"reader {reader.id!r} names an unknown section {reader.section!r}")
    if reader.id in _registry:
        raise ValueError(f"reader {reader.id!r} is registered twice")
    _registry[reader.id] = reader


def readers_for(section: str) -> list[Reader]:
    return [r for r in _registry.values() if r.section == section]


def register_platform_readers() -> None:
    """The real readers (R1-M4). Safe to call twice; the API calls it once at start-up."""
    from .amazon import AmazonReader
    from .flipkart import FlipkartCashbackReader, FlipkartSalesReader
    from .meesho import MeeshoReader

    for reader in (AmazonReader("b2c"), AmazonReader("b2b"), FlipkartSalesReader(), FlipkartCashbackReader(),
                   MeeshoReader("sales"), MeeshoReader("returns")):
        if reader.id not in _registry:
            register(reader)


def register_own_readers() -> None:
    """The seller's own invoices in our Excel template (R1-M5). Safe to call twice."""
    from .own_excel import OwnExcelReader

    reader = OwnExcelReader()
    if reader.id not in _registry:
        register(reader)


def register_readers() -> None:
    """Every real reader; the API calls it once at start-up."""
    register_platform_readers()
    register_own_readers()


def clear_for_tests() -> None:
    _registry.clear()
