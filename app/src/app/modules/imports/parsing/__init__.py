"""Turns an uploaded marketplace report into staged, validated rows.

Nothing here touches the database, stock or money. The output is a preview: every
source row with its raw values, its normalized values (when valid), its errors, and
a de-duplication key. Confirming rows into commerce is a later, separate step.

Column layouts are not hardcoded per marketplace. They live in mapping profiles
(profiles.py) because we have no verified sample reports yet (open question 2), and
guessing Amazon, Flipkart or Meesho headers would break CLAUDE.md rule 12.
"""

from .files import FileRejected, SourceTable, read_table
from .normalize import ParseResult, ParsedRow, RowStatus, parse
from .profiles import FieldKind, FieldSpec, MappingProfile, ProfileError

__all__ = [
    "FieldKind",
    "FieldSpec",
    "FileRejected",
    "MappingProfile",
    "ParseResult",
    "ParsedRow",
    "ProfileError",
    "RowStatus",
    "SourceTable",
    "parse",
    "read_table",
]
