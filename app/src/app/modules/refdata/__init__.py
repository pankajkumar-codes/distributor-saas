"""Reference data (LLD-0 §6.4): placeholder until S0b's loader lands.

Staff 2's S0b PR replaces this file with the real module. The signatures match it, so
no caller changes: `value_on` and `state_name` read the loaded rows; neither ever falls
back to a guessed default. Until then:

- `value_on` knows only the provisional product rows the S1 slices need, each as named
  here and in docs/OPEN_QUESTIONS.md, and raises RefdataMissing for every other key;
- `state_name` raises RefdataMissing for every code, because the state codes are tax
  reference data the GST expert cites (team/gst/gstin.md §3) and load through S0b.
"""

from datetime import date
from decimal import Decimal


class RefdataMissing(LookupError):
    def __init__(self, key: str, on: date):
        super().__init__(f"no reference data for {key!r} on {on.isoformat()}")
        self.key = key
        self.on = on


# kind: product, status: provisional (LLD-1 §12); the PO confirms before go-live.
_PROVISIONAL: dict[str, int] = {
    "identity.max_owned_businesses": 5,
}


def value_on(tx, key: str, on: date) -> Decimal | int | str | bool:  # noqa: ARG001
    try:
        return _PROVISIONAL[key]
    except KeyError:
        raise RefdataMissing(key, on) from None


def state_name(tx, code: str, on: date) -> str | None:  # noqa: ARG001
    raise RefdataMissing(f"state_codes.{code}", on)
