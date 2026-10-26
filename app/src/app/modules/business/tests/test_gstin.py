"""The GSTIN format check against team/gst/gstin.md §2 and §4 (AC-11), and the FY helpers."""

from datetime import date

import pytest

from app.modules.business.fiscal import fy_of, quarter_start
from app.modules.business.gstin import check_character, check_gstin, message

# gstin.md §2's publicly cited examples.
VALID = ["27AAPFU0939F1ZV", "29AAICA3918J1ZE", "29AACCF0683K1ZD", "27AAACR5055K1Z7"]


@pytest.mark.parametrize("gstin", VALID)
def test_the_cited_gstins_pass(gstin):
    check = check_gstin(gstin)
    assert (check.ok, check.normalised, check.state_code, check.errors, check.warnings) == (
        True, gstin, gstin[:2], [], []
    )
    assert check_character(gstin[:14]) == gstin[14]


def test_input_is_trimmed_uppercased_and_spaces_removed():  # gstin.md §4 item 1
    check = check_gstin(" 27aapfu0939f1zv ")
    assert check.ok and check.normalised == "27AAPFU0939F1ZV"
    assert check_gstin("27 AAPFU 0939 F1ZV").normalised == "27AAPFU0939F1ZV"


def test_a_wrong_check_character_is_refused_with_gstin_md_words():  # item 2
    check = check_gstin("27AAPFU0939F1ZA")
    assert not check.ok and check.errors == ["gstin_check_char"]
    assert message("gstin_check_char") == "GSTIN check character doesn't match; please re-check the number."


def test_length_and_shape_are_refused_first():
    short = check_gstin("27AAPFU0939F1Z")
    assert short.errors == ["gstin_length"] and short.state_code is None
    assert message("gstin_length", "27AAPFU0939F1Z") == "GSTIN has 14 characters; it needs 15."
    assert check_gstin("2AAAPFU0939F1ZV").errors == ["gstin_shape"]  # position 2 not a digit
    assert check_gstin("27AAPFU0939F0ZV").errors == ["gstin_shape"]  # position 13 may not be 0
    assert check_gstin("27AAPFU0939F1Z-").errors == ["gstin_shape"]
    assert check_gstin("").errors == ["gstin_length"]


def _with_check(first14: str) -> str:
    return first14 + check_character(first14)


def test_a_pan_part_that_is_neither_pan_nor_tan_warns_but_passes():  # item 5
    check = check_gstin(_with_check("27AAP1U0939F1Z"))
    assert check.ok and check.warnings == ["pan_shape"]
    tan = check_gstin(_with_check("27AAAA99999A1Z"))  # TAN-shaped: government TDS registrations
    assert tan.ok and tan.warnings == []


def test_a_14th_character_other_than_z_warns_only_for_the_business_itself():  # item 5
    gstin = _with_check("27AAPFU0939F1C")
    assert check_gstin(gstin).warnings == ["gstin_not_z"]
    assert check_gstin(gstin, own=False).warnings == []


def test_the_check_never_claims_more_than_format():  # item 6: no "verified" wording anywhere
    from app.modules.business import gstin

    assert not any("verif" in m.lower() or "active" in m.lower() for m in gstin.MESSAGES.values())


@pytest.mark.parametrize(
    ("day", "fy", "quarter"),
    [
        (date(2026, 4, 1), "2026-27", date(2026, 4, 1)),
        (date(2026, 3, 31), "2025-26", date(2026, 1, 1)),
        (date(2026, 12, 31), "2026-27", date(2026, 10, 1)),
        (date(2099, 8, 15), "2099-00", date(2099, 7, 1)),
    ],
)
def test_financial_year_and_quarter(day, fy, quarter):
    assert (fy_of(day), quarter_start(day)) == (fy, quarter)
