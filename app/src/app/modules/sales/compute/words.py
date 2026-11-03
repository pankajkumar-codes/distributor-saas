"""An amount in words with Indian numbering: thousand, lakh, crore (LLD-4 §3.2 step 8).

inr(Decimal("118000.50")) == "Rupees One Lakh Eighteen Thousand and Fifty Paise Only"
"""

from decimal import Decimal

from platform_common.money import MoneyError

_ONES = (
    "Zero One Two Three Four Five Six Seven Eight Nine Ten Eleven Twelve Thirteen Fourteen Fifteen Sixteen"
    " Seventeen Eighteen Nineteen"
).split()
_TENS = "_ _ Twenty Thirty Forty Fifty Sixty Seventy Eighty Ninety".split()
_HUNDRED, _THOUSAND, _LAKH, _CRORE = 100, 1000, 100_000, 10_000_000
_TWENTY, _TEN = 20, 10


def _below_hundred(n: int) -> str:
    if n < _TWENTY:
        return _ONES[n]
    tens, ones = divmod(n, _TEN)
    return _TENS[tens] + (f" {_ONES[ones]}" if ones else "")


def _words(n: int) -> str:
    parts = []
    if n >= _CRORE:
        parts.append(f"{_words(n // _CRORE)} Crore")
        n %= _CRORE
    for size, name in ((_LAKH, "Lakh"), (_THOUSAND, "Thousand"), (_HUNDRED, "Hundred")):
        if n >= size:
            parts.append(f"{_below_hundred(n // size)} {name}")
            n %= size
    if n or not parts:
        parts.append(_below_hundred(n))
    return " ".join(parts)


def inr(amount: Decimal) -> str:
    """Rupees and paise in words. The amount is already rounded to paise; a negative or a
    sub-paisa amount is a programming error."""
    if not isinstance(amount, Decimal) or amount < 0 or amount != amount.quantize(Decimal("0.01")):
        raise MoneyError(f"inr() takes a non-negative Decimal in paise: {amount!r}")
    rupees, paise = divmod(int(amount * _HUNDRED), _HUNDRED)
    text = f"Rupees {_words(rupees)}"
    if paise:
        text += f" and {_below_hundred(paise)} Paise"
    return text + " Only"
