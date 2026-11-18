"""What imports offers the rest of the app (LLD-3 §7.1: read_table, exposed in R1a for
catalog's product CSV; R3-M4: which marketplace files a period lacks, for the filing gate). The file readers are pure
functions over bytes; `missing_platform_months` reads the bound business's uploads, read-only.
"""

from ..parsing.files import FileRejected, SourceTable, read_table
from ..parsing.normalize import _looks_like_formula
from ..parsing.profiles import FieldKind
from .platform_files import missing_platform_months

__all__ = ["FileRejected", "SourceTable", "looks_like_formula", "missing_platform_months", "read_table"]


def looks_like_formula(value: str) -> bool:
    """A text cell a spreadsheet would run as a formula (=, @, + or - first, after folding
    look-alikes and hidden characters). Callers refuse it; nothing evaluates it."""
    return _looks_like_formula(value, FieldKind.text)
