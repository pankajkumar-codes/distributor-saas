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


def line(i, number):
    return SupplyLine("own_invoice", uuid.UUID(int=i), f"f.xlsx row {i}", GSTIN, date(2026, 10, 5), number, "invoice",
                      "B2CS", "19", Decimal("18"), "6109", "PCS", Decimal("1"), Decimal("100"), Decimal(),
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
