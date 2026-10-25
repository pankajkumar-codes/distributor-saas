"""Money is Decimal end to end; floats must never reach an authoritative amount."""

from decimal import ROUND_CEILING, ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal

import pytest

from platform_common.money import MoneyError, round_to_paise, to_decimal


@pytest.mark.parametrize("value", [0.1, 1.0, float("nan"), float("inf"), True, False])
def test_floats_and_bools_are_rejected(value):
    with pytest.raises(MoneyError):
        to_decimal(value)


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", "sNaN"])
def test_non_finite_strings_are_rejected(value):
    with pytest.raises(MoneyError):
        to_decimal(value)


@pytest.mark.parametrize("value", ["", "abc", "1,000.00", "₹10", " ", None])
def test_garbage_is_rejected(value):
    with pytest.raises(MoneyError):
        to_decimal(value)


@pytest.mark.parametrize(
    "value,expected",
    [("0.10", Decimal("0.10")), (10, Decimal("10")), (Decimal("-5.5"), Decimal("-5.5")), ("1e3", Decimal("1000"))],
)
def test_accepted_inputs(value, expected):
    assert to_decimal(value) == expected


def test_decimal_sum_is_exact_where_float_is_not():
    # The classic 0.1 + 0.2 trap: ten 0.10 line items must total exactly 1.00.
    assert sum((to_decimal("0.10") for _ in range(10)), Decimal("0")) == Decimal("1.00")


def test_rounding_mode_is_mandatory():
    with pytest.raises(TypeError):
        round_to_paise("1.005")  # no default on purpose: BUSINESS_RULES section 6 is open


def test_unsupported_rounding_mode_is_rejected():
    with pytest.raises(MoneyError):
        round_to_paise("1.005", rounding=ROUND_CEILING)


@pytest.mark.parametrize(
    "value,half_up,half_even",
    [
        ("1.005", "1.01", "1.00"),
        ("1.015", "1.02", "1.02"),
        ("1.025", "1.03", "1.02"),
        ("-1.005", "-1.01", "-1.00"),
        ("2.004", "2.00", "2.00"),
        ("2.006", "2.01", "2.01"),
        ("0", "0.00", "0.00"),
    ],
)
def test_rounding_vectors(value, half_up, half_even):
    # Mechanical vectors only. Which mode applies to tax, and at line or document
    # level, is an open decision; these do not assert any GST rule.
    assert round_to_paise(value, rounding=ROUND_HALF_UP) == Decimal(half_up)
    assert round_to_paise(value, rounding=ROUND_HALF_EVEN) == Decimal(half_even)


def test_rounding_also_rejects_floats():
    with pytest.raises(MoneyError):
        round_to_paise(1.005, rounding=ROUND_HALF_UP)


def test_result_always_has_two_decimal_places():
    assert str(round_to_paise(7, rounding=ROUND_HALF_UP)) == "7.00"
