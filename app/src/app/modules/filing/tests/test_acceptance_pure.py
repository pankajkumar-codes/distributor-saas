"""The export gate (R1-M8 S1): pure, no database."""

from decimal import Decimal
from types import SimpleNamespace

from app.modules.filing.checks import Finding
from app.modules.filing.gate import export_gate


def inst(status="open"):
    return SimpleNamespace(status=status)


def build(debit_notes=0, gap=Decimal("0")):
    return SimpleNamespace(debit_notes=debit_notes, gap=SimpleNamespace(is_zero=lambda: gap == 0))


def f(code, level, fp="a" * 64):
    return Finding(code, level, "m", (), fp)


def codes(g):
    return [r.code for r in g.reasons]


def test_a_clean_open_return_is_ready():
    g = export_gate(inst(), build(), [f("A-04", "info")], set())
    assert g.ready and g.to_accept == 0 and codes(g) == []


def test_a_warning_must_be_accepted_as_it_is_now():
    w = f("C-16", "warn")
    assert export_gate(inst(), build(), [w], set()).to_accept == 1
    assert not export_gate(inst(), build(), [w], set()).ready
    assert export_gate(inst(), build(), [w], {("C-16", "a" * 64)}).ready
    assert export_gate(inst(), build(), [w], {("C-16", "b" * 64)}).to_accept == 1  # changed since: not accepted


def test_a_block_stops_export_and_acceptance_never_helps():
    b = f("C-02", "block")
    g = export_gate(inst(), build(), [b], {("C-02", "a" * 64)})
    assert codes(g) == ["blocks"] and not g.ready


def test_debit_notes_refuse_export_with_no_accept_path():
    g = export_gate(inst(), build(debit_notes=2), [], set())
    assert codes(g) == ["debit_notes"] and "2 debit notes" in g.reasons[0].message and not g.ready


def test_a_locked_return_and_a_gap_each_refuse():
    assert codes(export_gate(inst("filed_locked"), build(), [], set())) == ["not_open"]
    assert codes(export_gate(inst(), build(gap=Decimal("0.01")), [], set())) == ["reconciliation"]
