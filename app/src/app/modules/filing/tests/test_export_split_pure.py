"""Splitting a file on document boundaries and the payment hook that fails closed (R1-M8 S4). Pure."""

import json
import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.modules.filing import entitlement
from app.modules.filing import export_model as em
from app.modules.filing import render_json as rj

from .test_render_json_pure import build_of

D = Decimal


def many():
    """20 B2B invoices (one of them at two rates) for three buyers, 2 credit notes, 2 B2CS rows: summaries of 4 rows."""
    from .test_gstr1_sections import CN, INV, SOAP, TEA, WB, A, B, line

    out = []
    for n in range(20):
        buyer = (A, B, "29AAACX4444D1ZP")[n % 3]
        out.append(line(f"INV-{n:02d}", 1 + n % 9, INV, "B2B", WB, SOAP, "1", "100.00", cgst="9.00", sgst="9.00",
                        value="118.00", buyer=buyer))  # fmt: skip
    out.append(line("INV-00", 1, INV, "B2B", WB, TEA, "1", "50.00", cgst="1.25", sgst="1.25", value="118.00", buyer=A))
    out.append(line("INV-B2C", 3, INV, "B2CS", WB, SOAP, "1", "100.00", cgst="9.00", sgst="9.00", value="118.00"))
    out.append(line("INV-B2C2", 3, INV, "B2CS", "29", SOAP, "1", "100.00", igst="18.00", value="118.00"))
    for k in range(2):
        out.append(line(f"CN-{k}", 12, CN, "CDNR", WB, SOAP, "1", "10.00", cgst="0.90", sgst="0.90", value="11.80",
                        buyer=A, original=("INV-00", date(2026, 10, 1))))  # fmt: skip
    return out


def model(lines=None):
    return em.export_model(build_of(lines or many()))


def docs_in(m):
    out = [i.number for p in m.b2b for i in p.invoices] + [i.number for g in m.b2cl for i in g.invoices]
    out += [n.number for p in m.cdnr for n in p.notes] + [n.number for n in m.cdnur]
    return out


def test_a_file_under_the_limit_is_one_part_and_unchanged():
    m = model()
    assert em.split(m, 1000) == [m]


@pytest.mark.parametrize("limit", [8, 9, 10, 13, 25])
def test_parts_are_cut_between_documents_never_inside_one_and_hold_every_row_once(limit):
    m = model()
    parts = em.split(m, limit)
    assert sorted(sum((docs_in(p) for p in parts), [])) == sorted(docs_in(m))  # every document once
    assert len(parts) > 1
    for p in parts:
        assert em.rows_in(p) <= limit
    assert sum(em.rows_in(p) for p in parts) == em.rows_in(m)
    # the summaries are once, in the last part
    assert [bool(p.b2cs or p.hsn_b2b or p.hsn_b2c) for p in parts][:-1] == [False] * (len(parts) - 1)
    assert parts[-1].b2cs == m.b2cs and parts[-1].hsn_b2b == m.hsn_b2b and parts[-1].hsn_b2c == m.hsn_b2c


def test_summaries_that_do_not_fit_with_the_last_documents_get_a_file_of_their_own():
    m = model()
    summaries = len(m.b2cs) + len(m.hsn_b2b) + len(m.hsn_b2c)
    parts = em.split(m, summaries)  # room for the summaries and nothing else
    assert all(em.rows_in(p) <= summaries for p in parts)
    last = parts[-1]
    assert docs_in(last) == [] and em.rows_in(last) == summaries


def test_summaries_longer_than_a_file_cannot_be_split_and_say_so():
    with pytest.raises(em.NotRenderable):
        em.split(model(), 3)


def test_every_part_is_a_valid_file_of_the_same_return():
    for part in em.split(model(), 9):
        d = json.loads(rj.render_json(part))
        assert d["gstin"] == model().gstin and d["fp"] == "102026" and d["filing_typ"] == "M"


def test_the_same_documents_regroup_under_their_recipient_in_each_part():
    m = model()
    whole = {(p.gstin, i.number) for p in m.b2b for i in p.invoices}
    parts = em.split(m, 9)
    got = {(p.gstin, i.number) for part in parts for p in part.b2b for i in p.invoices}
    assert got == whole


def test_a_limit_below_one_row_is_a_programming_error():
    with pytest.raises(ValueError):
        em.split(model(), 0)


# -- the payment hook: closed everywhere except demo and local runs -----------------------------------------------


def allowed():
    return entitlement.allowed(None, uuid.uuid4())


@pytest.fixture(autouse=True)
def _payments_on(monkeypatch):
    """The rule behind the placeholder: these tests are about what happens once `FREE_FOR_NOW` is removed."""
    monkeypatch.setattr(entitlement.plans, "FREE_FOR_NOW", False)


def test_while_free_for_now_every_business_may_download_in_any_environment(monkeypatch):
    monkeypatch.setattr(entitlement.plans, "FREE_FOR_NOW", True)
    monkeypatch.delenv("AWS_LAMBDA_FUNCTION_NAME", raising=False)
    for env in ("prod", "staging", ""):
        monkeypatch.setenv("PLATFORM_ENV", env)
        assert allowed() is True, env
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "worker")
    assert allowed() is True
    entitlement.set_check(lambda tx, b: False)  # a real check, once installed, still wins
    try:
        assert allowed() is False
    finally:
        entitlement.set_check(None)


def test_it_is_open_only_in_a_local_or_test_run(monkeypatch):
    monkeypatch.delenv("AWS_LAMBDA_FUNCTION_NAME", raising=False)
    for env, expected in (("local", True), ("test", True), ("dev", False), ("staging", False), ("prod", False),
                          ("production", False), ("", False), ("LOCAL ", False)):  # fmt: skip
        monkeypatch.setenv("PLATFORM_ENV", env)
        assert allowed() is expected, env


def test_it_is_closed_on_lambda_whatever_the_environment_says(monkeypatch):
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "worker")
    for env in ("local", "test", "prod"):
        monkeypatch.setenv("PLATFORM_ENV", env)
        assert allowed() is False


def test_a_missing_environment_on_lambda_is_closed_not_an_error(monkeypatch):
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "worker")
    monkeypatch.delenv("PLATFORM_ENV", raising=False)
    assert allowed() is False


def test_a_broken_check_closes_the_door_and_m9_can_install_and_remove_its_own(monkeypatch):
    monkeypatch.setenv("PLATFORM_ENV", "prod")
    monkeypatch.delenv("AWS_LAMBDA_FUNCTION_NAME", raising=False)
    try:
        entitlement.set_check(lambda tx, b: 1 / 0)
        assert allowed() is False
        entitlement.set_check(lambda tx, b: True)
        assert allowed() is True
    finally:
        entitlement.set_check(None)
    assert allowed() is False  # back to the default

