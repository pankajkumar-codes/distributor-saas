"""A made-up reader for tests (R1-M3). It stands in for the real platform readers (M4) so the
whole upload path can be exercised: detection by headers, the seller GSTIN, hold rules and
zero-value skips. Its layout is invented for tests and means nothing about any marketplace."""

import re

from app.modules.imports.models import StagedRowStatus
from app.modules.imports.parsing import FieldKind, FieldSpec, MappingProfile, SourceTable
from app.modules.imports.parsing.profiles import header_key

HEADERS = ("Seller Gstin", "Order Id", "Txn Type", "Qty", "Hsn", "Amount")


class TestReader:
    __test__ = False  # not a pytest class

    def __init__(self, reader_id="test_orders_v1", section="amazon", entry=r"orders.*\.csv"):
        self.id = reader_id
        self.section = section
        self.report_type = "orders"
        self._entry = re.compile(entry)

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
            report_type="orders",
            version="test-1",
            fields=(
                FieldSpec("seller_gstin", ("Seller Gstin",)),
                FieldSpec("order_id", ("Order Id",)),
                FieldSpec("txn_type", ("Txn Type",)),
                FieldSpec("qty", ("Qty",), required=False),
                FieldSpec("hsn", ("Hsn",), required=False),
                FieldSpec("amount", ("Amount",), FieldKind.decimal),
            ),
            dedup_key=("order_id",),
            verified=True,  # the profile's own claim; the refdata row decides whether it counts
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
