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
HOLD_REASONS = ("blank_hsn", "blank_uqc", "unknown_state", "unknown_txn_type", "blank_qty", "sanity")


class Reader(Protocol):
    id: str  # e.g. "amazon_mtr_b2c_v1"; also the refdata key stem imports.profile.<id>
    section: str
    report_type: str  # coverage: which report this file is (e.g. "mtr_b2c")

    def accepts(self, name: str) -> bool:
        """For a zip: is this entry one of this reader's files, by exact file name pattern."""

    def detect(self, table: SourceTable) -> bool:
        """Does this file carry the headers this reader requires?"""

    def profile(self) -> MappingProfile: ...

    def gstin(self, table: SourceTable) -> str | None:
        """The seller GSTIN the file states (its own header block or column), or None."""

    def classify(self, row: ParsedRow) -> "tuple[StagedRowStatus, str | None] | None":
        """The hold rule, for a row that parsed as valid: (held, reason) with a reason from
        HOLD_REASONS, (skipped_zero, None) for a zero-value cancel or replacement, or None."""


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

    for reader in (AmazonReader("b2c"), AmazonReader("b2b")):
        if reader.id not in _registry:
            register(reader)


def clear_for_tests() -> None:
    _registry.clear()
