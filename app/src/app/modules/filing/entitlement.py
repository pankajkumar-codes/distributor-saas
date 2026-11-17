"""Who may download a GSTR-1 file: the payment hook (R1-M8; the real rule is R1-M9).

Until M9 sets a check, a download is allowed only where `debug_env()` is true (PLATFORM_ENV local or test, and never on
Lambda), so the demo and local runs work and every deployed environment stays closed. The default fails closed: no
environment variable, a mistake in configuration or a missing check all mean "not allowed".
"""

import uuid
from collections.abc import Callable

from sqlalchemy.orm import Session

from platform_common.auth import debug_env

Check = Callable[[Session, uuid.UUID], bool]


def _demo_only(tx: Session, business_id: uuid.UUID) -> bool:  # noqa: ARG001 (M9 will look at the business)
    return debug_env()


_check: Check = _demo_only


def allowed(tx: Session, business_id: uuid.UUID) -> bool:
    try:
        return bool(_check(tx, business_id))
    except Exception:  # noqa: BLE001  (a broken check must close the door, not open it)
        return False


def set_check(check: Check | None) -> None:
    """M9 installs its rule here; None puts back the default."""
    global _check
    _check = check or _demo_only
