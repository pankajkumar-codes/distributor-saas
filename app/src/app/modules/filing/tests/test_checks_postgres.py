"""Checks that read refdata, on PostgreSQL. Skipped unless PG_ADMIN_URL is set."""

import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session

from app.modules.filing import checks
from app.modules.filing.gstr1 import SupplyLine

from .conftest import PG_ADMIN_URL, ctx, new_business, user_id

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")
GSTIN = "19AAPFU0939F1ZS"


def line(i, number, *, pos="19", hsn="6109"):
    return SupplyLine("own_invoice", uuid.UUID(int=i), f"f.xlsx row {i}", GSTIN, date(2026, 10, 5), number, "invoice",
                      "B2CS", pos, Decimal("18"), hsn, "PCS", Decimal("1"), Decimal("100"), Decimal(),
                      Decimal("9"), Decimal("9"), Decimal(), Decimal("118"))


def test_a_number_over_the_rule_or_with_other_characters_is_a_block_level_finding(pg):
    """A file's over-long number is held at reading, so the check is fed lines the way a sales document could be."""
    biz = new_business(pg, "alice")
    fake = SimpleNamespace(lines=(line(1, "INV-12345678901234567"), line(2, "INV#1"), line(3, "INV-1")),
                           instance=SimpleNamespace(period_end=date(2026, 10, 31)))
    with pg.app_rw.begin() as c:
        ctx(c, user_id(pg.owner, "alice"), biz)
        found = checks.c03_document_number(Session(bind=c), fake)
    assert [f.source_refs for f in found] == [("f.xlsx row 1",), ("f.xlsx row 2",)]
    assert all(f.code == "C-03" and f.level == "block" and f.needs_ca_check for f in found)


def test_an_unknown_place_of_supply_is_a_block_level_finding(pg):
    biz = new_business(pg, "alice")
    fake = SimpleNamespace(lines=(line(1, "INV-1", pos="99"), line(2, "INV-2", pos="29")))
    with pg.app_rw.begin() as c:
        ctx(c, user_id(pg.owner, "alice"), biz)
        found = checks.c05_place_of_supply(Session(bind=c), fake)
    assert [f.source_refs for f in found] == [("f.xlsx row 1",)] and found[0].level == "block"


def test_an_hsn_below_the_minimum_digits_is_reported_and_marked_for_the_ca_while_the_band_is_unset(pg):
    """The same answer for every row of one build: the band is read once, not per month seen so far."""
    biz = new_business(pg, "alice")
    fake = SimpleNamespace(lines=(line(1, "INV-1", hsn="61"), line(2, "INV-2", hsn="6109"), line(3, "INV-3", hsn="610910")))
    with pg.app_rw.begin() as c:
        ctx(c, user_id(pg.owner, "alice"), biz)
        found = checks.c10_hsn_digits(Session(bind=c), fake)
    assert found and all(f.code == "C-10" and f.level == "block" for f in found)
    assert "f.xlsx row 1" in {r for f in found for r in f.source_refs}
    assert len({f.needs_ca_check for f in found}) == 1


def test_a_return_with_more_rows_than_one_file_holds_is_a_warning_that_names_the_split(pg):
    biz = new_business(pg, "alice")
    on = SimpleNamespace(period_end=date(2026, 10, 31))
    with pg.app_rw.begin() as c:
        ctx(c, user_id(pg.owner, "alice"), biz)
        tx = Session(bind=c)
        limit = int(checks.value_on(tx, "gstr1.offline_tool.max_lines", on.period_end))
        at = checks.c13_line_items(tx, SimpleNamespace(instance=on, line_items=limit))
        over = checks.c13_line_items(tx, SimpleNamespace(instance=on, line_items=limit + 1))
    assert at == []
    (f,) = over
    assert f.code == "C-13" and f.level == "warn" and f.needs_ca_check
    assert str(limit + 1) in f.message and "several files" in f.message and "5 MB" in f.message


def _iff(taxable_rows, form="IFF"):
    from app.modules.filing.gstr1 import Amounts, B2BRow, Gstr1Sections

    rows = tuple(B2BRow("29AAAAA0000A1Z5", None, f"I{i}", date(2026, 10, 5), Decimal(), "29", Decimal("18"),
                        Amounts(Decimal(t)), (f"f.xlsx row {i}",)) for i, t in enumerate(taxable_rows, 1))
    return SimpleNamespace(instance=SimpleNamespace(period_end=date(2026, 10, 31), form=form),
                           sections=Gstr1Sections(kind="IFF", b2b=rows))


def test_an_iff_over_the_b2b_limit_is_a_warning_and_at_the_limit_or_a_monthly_return_is_not(pg):
    biz = new_business(pg, "alice")
    with pg.app_rw.begin() as c:
        ctx(c, user_id(pg.owner, "alice"), biz)
        tx = Session(bind=c)
        cap = Decimal(checks.value_on(tx, "iff.max_taxable_value", date(2026, 10, 31)))
        at = checks.c11_iff_cap(tx, _iff([str(cap)]))
        over = checks.c11_iff_cap(tx, _iff([str(cap - 1), "1.01"]))
        monthly = checks.c11_iff_cap(tx, _iff([str(cap + 1)], form="GSTR1"))
    assert at == [] and monthly == []
    (f,) = over
    assert f.code == "C-11" and f.level == "warn" and f.needs_ca_check
    assert f.source_refs == ("f.xlsx row 1", "f.xlsx row 2") and str(cap) in f.message
