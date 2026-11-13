"""What every platform reader shares (R1-M4): find the header row by name, read the seller's GSTIN
from its column, accept a zip entry by file name. A reader built on it is data (its profile) plus
its hold rule; it never touches the database or the object store, never logs a cell, and a file
whose headers it does not find is not its file."""

import re

from ..parsing import MappingProfile, SourceTable
from ..parsing.profiles import header_key

MIXED_GSTINS = "MIXED"  # never a valid GSTIN, so a file naming several sellers is refused as wrong_gstin
HEADER_ROWS = 10  # how far down a report's title lines the header row may sit


class HeaderReader:
    id: str
    section: str
    report_type: str

    def __init__(self, *, entry: str, markers: tuple[str, ...], excluded: tuple[str, ...] = (), gstin_header: str):
        """`entry`: regex a zip entry's whole name must match. `markers`: headers that must all be
        present for a file to be this reader's. `excluded`: headers that, if present, make it another
        reader's (so two readers of one family never both claim a file)."""
        self._entry = re.compile(entry, re.IGNORECASE)
        self._markers = tuple(header_key(h) for h in markers)
        self._excluded = tuple(header_key(h) for h in excluded)
        self._gstin = header_key(gstin_header)

    def profile(self) -> MappingProfile:  # pragma: no cover - the readers define it
        raise NotImplementedError

    def accepts(self, name: str) -> bool:
        return bool(self._entry.fullmatch(name))

    def _header(self, table: SourceTable) -> tuple[int, list[str]] | None:
        for i, row in enumerate(table.rows[:HEADER_ROWS]):
            keys = [header_key(c) for c in row]
            if all(m in keys for m in self._markers) and not any(x in keys for x in self._excluded):
                return i, keys
        return None

    def detect(self, table: SourceTable) -> bool:
        return self._header(table) is not None

    def gstin(self, table: SourceTable) -> str | None:
        found = self._header(table)
        if found is None or self._gstin not in found[1]:
            return None
        col = found[1].index(self._gstin)
        seen = []
        for row in table.rows[found[0] + 1 :]:
            if len(row) > col and row[col].strip() and row[col].strip() not in seen:
                seen.append(row[col].strip())
        if len(seen) > 1:
            return MIXED_GSTINS  # one file, several sellers: refused whole as another business's file
        return seen[0] if seen else None
