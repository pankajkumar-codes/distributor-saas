"""What imports offers the rest of the app (LLD-3 §7.1: read_table, exposed in R1a for
catalog's product CSV). Pure functions over bytes: no database, no profile.
"""

from ..parsing.files import FileRejected, SourceTable, read_table
from ..parsing.normalize import _looks_like_formula
from ..parsing.profiles import FieldKind

__all__ = ["FileRejected", "SourceTable", "looks_like_formula", "read_table"]


def looks_like_formula(value: str) -> bool:
    """A text cell a spreadsheet would run as a formula (=, @, + or - first, after folding
    look-alikes and hidden characters). Callers refuse it; nothing evaluates it."""
    return _looks_like_formula(value, FieldKind.text)
