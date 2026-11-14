"""Demo readers for the local demo (`demo.ps1`, `make demo`). Never in AWS.

R1-M3 ships the upload pipeline with no real marketplace reader (Amazon, Flipkart and Meesho
arrive in R1-M4), so a local demo has nothing to read a file with. These stand-ins read one
invented layout, "demo orders", named `demo-*.csv`, so the whole path (upload, parse, held
rows, discard, decide a row) can be tried by hand. The layout means nothing about any real
marketplace and every sample file is made up. Registered only when `DEMO_READERS=1` and the
environment is local or test (`debug_env`, which is never true on Lambda); the readers are
unverified (no refdata `imports.profile.<id>.verified` row), so runs say so.
"""

import os
import re

from app.modules.imports.models import StagedRowStatus
from app.modules.imports.parsing import FieldKind, FieldSpec, MappingProfile, SourceTable
from app.modules.imports.parsing.profiles import header_key
from app.modules.imports.readers import PLATFORM_SECTIONS, readers_for, register
from platform_common.auth import debug_env

HEADERS = ("Seller Gstin", "Order Id", "Txn Type", "Qty", "Hsn", "Amount")


class DemoReader:
    report_type = "orders"

    def __init__(self, section: str):
        self.section = section
        self.id = f"demo_{section}_orders_v1"
        self._entry = re.compile(r"demo-.*\.csv")

    def accepts(self, name: str) -> bool:
        return bool(self._entry.fullmatch(name))

    def _header_index(self, table: SourceTable):
        for i, row in enumerate(table.rows[:5]):
            keys = [header_key(c) for c in row]
            if all(header_key(h) in keys for h in HEADERS):
                return i, keys
        return None

    def detect(self, table: SourceTable) -> bool:
        return self._header_index(table) is not None

    def gstin(self, table: SourceTable) -> str | None:
        found = self._header_index(table)
        if found is None:
            return None
        i, keys = found
        col = keys.index(header_key("Seller Gstin"))
        for row in table.rows[i + 1 :]:
            if len(row) > col and row[col].strip():
                return row[col].strip()
        return None

    def profile(self) -> MappingProfile:
        return MappingProfile(
            marketplace=self.section,
            report_type=self.report_type,
            version="demo-1",
            fields=(
                FieldSpec("seller_gstin", ("Seller Gstin",)),
                FieldSpec("order_id", ("Order Id",)),
                FieldSpec("txn_type", ("Txn Type",)),
                FieldSpec("qty", ("Qty",), required=False),
                FieldSpec("hsn", ("Hsn",), required=False),
                FieldSpec("amount", ("Amount",), FieldKind.decimal),
            ),
            dedup_key=("order_id",),
            verified=False,  # an invented layout is never verified
        )

    def classify(self, row):
        n = row.normalized or {}
        if n.get("txn_type") in ("Cancel", "FreeReplacement") and str(n.get("amount")) in ("0", "0.00"):
            return StagedRowStatus.skipped_zero, None
        if not n.get("hsn"):
            return StagedRowStatus.held, "blank_hsn"
        if not n.get("qty"):
            return StagedRowStatus.held, "blank_qty"
        return None


def register_demo_readers() -> bool:
    """Registers the demo readers if this is a local run that asked for them."""
    if os.environ.get("DEMO_READERS") != "1" or not debug_env():
        return False
    for section in PLATFORM_SECTIONS:
        reader = DemoReader(section)
        if all(r.id != reader.id for r in readers_for(section)):  # importing the app twice must not fail
            register(reader)
    return True
