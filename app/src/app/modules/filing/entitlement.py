"""Who may download a GSTR-1 file: the payment hook (R1-M8; R1-M9 opens it while plans are free).

While `plans.FREE_FOR_NOW` is true (R1: no payment provider yet) every business may download. When it is false the
default is the fail-closed rule: a download is allowed only where `debug_env()` is true (PLATFORM_ENV local or test, and
never on Lambda) unless a real check was installed with `set_check`. A mistake in configuration, a missing check or an error
in the check all mean "not allowed".
"""

import uuid
from collections.abc import Callable

from sqlalchemy.orm import Session

from platform_common.auth import debug_env

from . import plans

Check = Callable[[Session, uuid.UUID], bool]


def _demo_only(tx: Session, business_id: uuid.UUID) -> bool:  # noqa: ARG001 (a payment provider will look at the business)
    return plans.FREE_FOR_NOW or debug_env()


_check: Check = _demo_only


def allowed(tx: Session, business_id: uuid.UUID) -> bool:
    try:
        return bool(_check(tx, business_id))
    except Exception:  # noqa: BLE001  (a broken check must close the door, not open it)
        return False


def set_check(check: Check | None) -> None:
    """The payment provider integration installs its rule here; None puts back the default."""
    global _check
    _check = check or _demo_only


# The invoicing plan's hook (R2-M7): may this business finalize invoices beyond the free ones? Same rule as above: open while
# payments are a placeholder, closed (fail-closed) when they are not and no real check was installed.
_invoice_check: Check = _demo_only


def invoicing_allowed(tx: Session, business_id: uuid.UUID) -> bool:
    try:
        return bool(_invoice_check(tx, business_id))
    except Exception:  # noqa: BLE001  (a broken check must close the door, not open it)
        return False


def set_invoice_check(check: Check | None) -> None:
    global _invoice_check
    _invoice_check = check or _demo_only
