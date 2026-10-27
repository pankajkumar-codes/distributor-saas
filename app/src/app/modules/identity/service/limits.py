"""The auth limits in force today, from refdata (LLD-1 L1-10, §12; LLD-0 §6.5).

They're read in their own short read-only transaction because rate.hit commits its
counter before the request's first unit of work opens. The reader caches the loaded
rows, so this is one small query per request.
"""

from datetime import date

from platform_common.uow import Principal, unit_of_work

from app.modules.refdata import value_on


def read(keys: tuple[str, ...], today: date, request_id: str) -> dict[str, int]:
    """{key: value} for each `auth.*` key. Raises RefdataMissing (a 500, never a guess)."""
    with unit_of_work(Principal(user_sub=None, request_id=request_id), read_only=True) as uow:
        return {key: value_on(uow.tx, key, today) for key in keys}
