"""Money is always Decimal. Floats are rejected outright.

The rounding rule (half-up vs half-even, line vs document level) is an open
business decision (docs/BUSINESS_RULES.md section 6), so callers must pass it
explicitly instead of relying on a default.
"""

from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal, InvalidOperation

PAISE = Decimal("0.01")
ALLOWED_ROUNDING = {ROUND_HALF_UP, ROUND_HALF_EVEN}


class MoneyError(ValueError):
    pass


def to_decimal(value: Decimal | int | str) -> Decimal:
    if isinstance(value, bool) or isinstance(value, float):
        raise MoneyError("money must not be a float or bool; pass a str, int or Decimal")
    try:
        result = Decimal(value)
    except (InvalidOperation, TypeError) as exc:
        raise MoneyError(f"not a valid amount: {value!r}") from exc
    if not result.is_finite():
        raise MoneyError(f"not a finite amount: {value!r}")
    return result


def round_to_paise(value: Decimal | int | str, *, rounding: str) -> Decimal:
    if rounding not in ALLOWED_ROUNDING:
        raise MoneyError(f"unsupported rounding mode: {rounding}")
    return to_decimal(value).quantize(PAISE, rounding=rounding)
