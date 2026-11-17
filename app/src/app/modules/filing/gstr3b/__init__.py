"""GSTR-3B worksheet (R1-M8b): numbers to check and key into the GST portal. Never a filing.

Pure functions only here (no database, no refdata): `build_outward` turns the GSTR-1 section rows into Table 3.1(a) and 3.2,
and `labels` holds the form's row names. The seller's own entries (ITC, Table 5, interest) are stored by the service layer.
"""

from .worksheet import FLAG_TEXT, InterStateRow, Outward, build_outward

__all__ = ["FLAG_TEXT", "InterStateRow", "Outward", "build_outward"]
