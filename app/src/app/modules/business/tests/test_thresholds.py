"""business.hsn_min_digits and business.einvoice_status (LLD-1 §8.3, erratum S-3).

The decision tables run without a database; the PostgreSQL tests read real bands and the
refdata rows from refdata/values (skipped unless PG_ADMIN_URL is set). Thresholds below
are fixtures for the tables; the PostgreSQL tests use the cited rows.
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.modules.business.thresholds import einvoice_status_for, min_digits_for

from .conftest import PG_ADMIN_URL, ctx, user_id

D = Decimal
FIVE_CRORE, TEN_CRORE = D("50000000.00"), D("100000000.00")


@pytest.mark.parametrize(
    "band, band_threshold, rule_threshold, digits",
    [
        ("up_to_threshold", FIVE_CRORE, FIVE_CRORE, 4),
        ("above_threshold", FIVE_CRORE, FIVE_CRORE, 6),
        (None, FIVE_CRORE, FIVE_CRORE, 6),  # no band: the stricter row (LLD-1 §8.3)
        ("up_to_threshold", TEN_CRORE, FIVE_CRORE, 6),  # up to ₹10 crore doesn't say under ₹5 crore
        ("up_to_threshold", FIVE_CRORE, TEN_CRORE, 4),  # up to ₹5 crore is under ₹10 crore
        ("above_threshold", FIVE_CRORE, TEN_CRORE, 6),  # unsettled: stricter
    ],
)
def test_min_digits_table(band, band_threshold, rule_threshold, digits):
    assert min_digits_for(band, band_threshold, rule_threshold, 4, 6) == digits


@pytest.mark.parametrize(
    "history, above, band_threshold, rule_threshold, status",
    [
        ("yes", False, FIVE_CRORE, FIVE_CRORE, "applies"),
        ("no", True, FIVE_CRORE, FIVE_CRORE, "applies"),  # an earlier FY's band above the threshold
        ("no", True, FIVE_CRORE, D("1000000000.00"), "unsure"),  # above ₹5 crore may not be above ₹100 crore
        ("no", True, TEN_CRORE, FIVE_CRORE, "applies"),  # above ₹10 crore is above ₹5 crore
        ("no", False, TEN_CRORE, FIVE_CRORE, "no"),  # the answer stands when no band is above
        ("not_sure", True, FIVE_CRORE, D("1000000000.00"), "unsure"),
        ("no", False, FIVE_CRORE, FIVE_CRORE, "no"),
        ("not_sure", False, FIVE_CRORE, FIVE_CRORE, "unsure"),
        (None, False, FIVE_CRORE, FIVE_CRORE, "unsure"),
    ],
)
def test_einvoice_status_table(history, above, band_threshold, rule_threshold, status):
    assert einvoice_status_for(history, above, band_threshold, rule_threshold) == status


# -- PostgreSQL --------------------------------------------------------------------------
pg_only = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")


@pytest.fixture()
def business(pg):
    from .test_create_business_postgres import create

    r = create(pg.client)
    assert r.status_code == 201, r.text
    return pg, uuid.UUID(r.json()["business_id"]), user_id(pg.owner, "alice")


def set_band(pg, bid, alice, fy, band):
    with pg.owner.begin() as c:
        c.execute(
            text(
                "insert into business.turnover_bands (business_id, fy, band, set_by) values (:b, :fy, :band, :u)"
                " on conflict (business_id, fy) do update set band = excluded.band"
            ),
            {"b": bid, "fy": fy, "band": band, "u": alice},
        )


def ask(pg, bid, alice, on):
    from app.modules.business.interface import einvoice_status, hsn_min_digits

    with pg.app_rw.begin() as c:
        ctx(c, alice, bid)
        return hsn_min_digits(c, on), einvoice_status(c, on)


@pg_only
def test_digits_follow_the_preceding_fy_band(business):
    pg, bid, alice = business
    on = date(2026, 10, 20)  # FY 2026-27: the 2025-26 band decides
    set_band(pg, bid, alice, "2025-26", "up_to_threshold")
    set_band(pg, bid, alice, "2026-27", "above_threshold")  # this FY's turnover counts from next FY
    assert ask(pg, bid, alice, on)[0] == 4
    assert ask(pg, bid, alice, date(2027, 4, 1))[0] == 6
    assert ask(pg, bid, alice, date(2025, 10, 1))[0] == 6  # no 2024-25 band: the stricter count


@pg_only
def test_einvoicing_from_the_answer_or_any_earlier_band(business):
    pg, bid, alice = business
    on = date(2026, 10, 20)
    assert ask(pg, bid, alice, on)[1] == "no"  # the sign-up body answers "no", band up to the limit
    set_band(pg, bid, alice, "2026-27", "above_threshold")
    assert ask(pg, bid, alice, on)[1] == "no"  # crossing this FY counts only from the next
    set_band(pg, bid, alice, "2019-20", "above_threshold")
    assert ask(pg, bid, alice, on)[1] == "applies"  # refdata-lld4.md §2's example: any FY since 2017-18
    with pg.owner.begin() as c:
        c.execute(text("delete from business.turnover_bands where fy = '2019-20'"))
        c.execute(text("update business.profiles set einvoice_history = 'not_sure' where business_id = :b"), {"b": bid})
    assert ask(pg, bid, alice, on)[1] == "unsure"


@pg_only
def test_another_business_s_bands_are_not_read(business):
    pg, bid, alice = business
    set_band(pg, bid, alice, "2025-26", "up_to_threshold")
    other = uuid.uuid4()
    assert ask(pg, other, alice, date(2026, 10, 20)) == (6, "unsure")  # nothing visible: strictest answers
