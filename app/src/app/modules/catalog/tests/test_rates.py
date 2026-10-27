"""Rate history rules without a database (LLD-3 §3, AC3-1; §13's warning window and
void-in-the-middle cases), and the UQC list pinned to the GSTR-1 template."""

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from platform_common.errors import Invalid

from ..rates import RateRow, parse_rate, rate_on, valid_until

REPO = Path(__file__).resolve().parents[6]


def row(i, rate, valid_from, voided=False, confirmed=False):
    return RateRow(i, Decimal(rate), date.fromisoformat(valid_from), voided, confirmed)


ROWS = [row(1, "12", "2024-04-01"), row(2, "18", "2025-09-22"), row(3, "5", "2026-12-01")]


def test_the_rate_on_a_date_is_the_latest_live_row_on_or_before_it():
    assert rate_on(ROWS, date(2024, 3, 31), 30) is None  # before the first row: no_rate_on_date
    assert rate_on(ROWS, date(2024, 4, 1), 30).row.id == 1
    assert rate_on(ROWS, date(2025, 9, 21), 30).row.id == 1
    assert rate_on(ROWS, date(2025, 9, 22), 30).row.id == 2
    # A future-dated row leaves today's rate alone until its date.
    assert rate_on(ROWS, date(2026, 11, 30), 30).row.id == 2
    assert rate_on(ROWS, date(2026, 12, 1), 30).row.id == 3


def test_a_voided_row_is_never_returned_and_the_earlier_row_covers_the_gap():
    rows = [ROWS[0], row(2, "18", "2025-09-22", voided=True), ROWS[2]]
    assert rate_on(rows, date(2025, 10, 1), 30).row.id == 1
    assert valid_until(rows) == {1: date(2026, 12, 1), 3: None}
    assert valid_until(ROWS) == {1: date(2025, 9, 22), 2: date(2026, 12, 1), 3: None}


@pytest.mark.parametrize(("days", "warns"), [(0, True), (29, True), (30, True), (31, False)])
def test_the_rate_change_warning_window_is_inclusive(days, warns):
    on = date(2025, 9, 22) + timedelta(days=days)
    assert rate_on(ROWS, on, 30).changed_within_warning_window is warns


def test_a_first_rate_is_not_a_change():
    assert rate_on([ROWS[0]], date(2024, 4, 2), 30).changed_within_warning_window is False


def test_rates_parse_as_decimal_strings_only():
    assert parse_rate("18.00") == Decimal("18") and parse_rate(" 0.25 ") == Decimal("0.25")
    for bad in ("", "eighteen", "NaN", "Infinity", 18.0, 18):
        with pytest.raises(Invalid):
            parse_rate(bad)


def test_uqc_descriptions_match_the_gstr1_template_master_sheet():
    """GST expert v1.1, EM 2026-10-27: code + "-" + official_description is the string the
    GSTR-1 template's UQC list carries, for every code and no others."""
    units = yaml.safe_load((REPO / "refdata" / "uqc_codes.yaml").read_text())
    ours = sorted(f"{u['code']}-{u['official_description']}" for u in units)
    fixture = Path(__file__).with_name("fixtures") / "gstr1_v2_2_master_uqc.txt"
    template = sorted(line for line in fixture.read_text().splitlines() if line and not line.startswith("#"))
    assert len(template) == 45
    assert ours == template
