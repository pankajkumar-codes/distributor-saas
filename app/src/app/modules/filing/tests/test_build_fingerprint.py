"""The build fingerprint: stable for the same lines in any order, different for one paisa or one line more."""

import uuid
from dataclasses import replace
from datetime import date
from decimal import Decimal

from app.modules.filing import build
from app.modules.filing.gstr1 import SupplyLine
from app.modules.filing.periods import ReturnInstance

INST = ReturnInstance(uuid.UUID(int=1), "19AAPFU0939F1ZS", "GSTR1", "2026-10", date(2026, 10, 1), date(2026, 10, 31),
                      None, "open")


def ln(n, taxable="100.00"):
    return SupplyLine("own_invoice", uuid.UUID(int=n), f"f.xlsx row {n}", INST.gstin, date(2026, 10, 5), f"INV-{n}",
                      "invoice", "B2CS", "19", Decimal("18"), "6109", "PCS", Decimal("1"), Decimal(taxable),
                      Decimal(), Decimal("9"), Decimal("9"), Decimal(), Decimal("118"))


def test_the_fingerprint_ignores_order_and_moves_with_one_paisa_or_one_line():
    a, b = ln(1), ln(2)
    base = build._fingerprint(INST, [a, b], 0)
    assert base == build._fingerprint(INST, [b, a], 0)
    assert base != build._fingerprint(INST, [replace(a, taxable_value=Decimal("100.01")), b], 0)
    assert base != build._fingerprint(INST, [a], 0)
    assert base != build._fingerprint(INST, [a, b], 1)  # a debit note confirmed later changes the return too
