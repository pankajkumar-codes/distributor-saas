"""refdata: dated, cited reference data every module reads (LLD-0 §6.4).

    from app.modules.refdata import value_on, RefdataMissing

The migrator loads the rows from refdata/*.yaml (migrator/migrator/refdata.py); this
module only reads them. No row covering the date, or two, raises RefdataMissing: a
500 and an alarm, never a guessed default.
"""

from .reader import (
    RefdataMissing,
    RefdataUnconfirmed,
    gst_rates,
    require_confirmed,
    state_codes,
    state_name,
    uqc_codes,
    uqc_name,
    value_on,
)

__all__ = [
    "RefdataMissing",
    "RefdataUnconfirmed",
    "gst_rates",
    "require_confirmed",
    "state_codes",
    "state_name",
    "uqc_codes",
    "uqc_name",
    "value_on",
]
