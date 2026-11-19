"""GSTIN lookup: fetch a business's registered details from a provider so sign-up can fill the form (#249, D-100).

A lookup is a convenience, never a check. The result is shown to the person, who confirms or types over it; nothing is
stored from the lookup itself, and nothing here may be worded as "verified" (GC-P6: only the format and check digit are
checked by us). Only the 15-character GSTIN is ever sent to a provider: no user, business or invoice data.

Providers sit behind `LookupProvider`. Which one runs is the deployment setting `GSTIN_LOOKUP_PROVIDER`:

- unset or `off`: the lookup is switched off (the route answers 503 `lookup_off`, the form says nothing and the person types).
- `fake`: a local provider that invents plausible details from the GSTIN itself. Local and test environments only.
- a vendor name: not built yet. D-100 chooses a GSP-backed paid API and the adapter is written against the vendor's own
  sample response once Pankaj has an account (docs/GSTIN_LOOKUP.md). Naming one before then fails loudly at start-up
  of the first request rather than falling back to the fake.
"""

import os
from dataclasses import dataclass
from functools import cache
from typing import Protocol

from platform_common.auth import debug_env


class LookupOff(Exception):
    """No provider is configured: the feature is off."""


class LookupUnavailable(Exception):
    """The provider could not answer (down, timed out, refused, or sent something we cannot read)."""


@dataclass(frozen=True)
class Address:
    line1: str | None = None
    line2: str | None = None
    city: str | None = None
    pin: str | None = None
    state_code: str | None = None


@dataclass(frozen=True)
class Taxpayer:
    gstin: str
    legal_name: str | None
    trade_name: str | None
    status: str | None  # the provider's word, e.g. "Active", "Cancelled"; shown as is, never interpreted
    address: Address


class LookupProvider(Protocol):
    name: str

    def lookup(self, gstin: str) -> Taxpayer | None:
        """The record for a GSTIN that already passed our format check, or None when the provider has no such GSTIN.
        Raises LookupUnavailable for anything else going wrong."""


# --- The fake provider (local and test only) -----------------------------------------------------------------------

_PIN = {"19": "700001", "07": "110001", "27": "400001", "29": "560001", "33": "600001", "24": "380001", "09": "226001"}
_CITY = {"19": "Kolkata", "07": "New Delhi", "27": "Mumbai", "29": "Bengaluru", "33": "Chennai", "24": "Ahmedabad", "09": "Lucknow"}


class FakeProvider:
    """Made-up details, the same every time for the same GSTIN, so a demo and a test can rely on them.

    The 13th character (the entity's registration number within its PAN) picks a case a person might meet:
    `9` is a GSTIN the provider does not know, `8` is a cancelled registration, `7` is the provider being down,
    anything else is an active taxpayer. Never returns real data.
    """

    name = "demo"

    def lookup(self, gstin: str) -> Taxpayer | None:
        case = gstin[12]
        if case == "9":
            return None
        if case == "7":
            raise LookupUnavailable("fake provider: simulated outage")
        state = gstin[:2]
        pan = gstin[2:12]
        return Taxpayer(
            gstin=gstin,
            legal_name=f"Demo Traders {pan} Private Limited",
            trade_name=f"Demo Traders {pan[:5]}",
            status="Cancelled" if case == "8" else "Active",
            address=Address(
                line1="12 Sample Road",
                line2="Demo Market",
                city=_CITY.get(state, "Demo City"),
                pin=_PIN.get(state, "110001"),
                state_code=state,
            ),
        )


@cache
def provider() -> LookupProvider:
    """The configured provider. Raises LookupOff when none is."""
    choice = (os.environ.get("GSTIN_LOOKUP_PROVIDER") or "off").strip().lower()
    if choice == "off":
        raise LookupOff
    if choice == "fake":
        if not debug_env():
            raise RuntimeError("GSTIN_LOOKUP_PROVIDER=fake is for local and test environments only")
        return FakeProvider()
    raise RuntimeError(f"GSTIN_LOOKUP_PROVIDER={choice!r}: no such provider is built (see docs/GSTIN_LOOKUP.md)")
