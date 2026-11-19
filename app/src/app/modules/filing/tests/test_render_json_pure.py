"""The GSTR-1 JSON file from a build (R1-M8 S3). Pure; the figures are gstr1-examples Part A (the masked synthetic set)."""

import json
import random
import uuid
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.modules.filing import export_model as em
from app.modules.filing import render_json as rj
from app.modules.filing.build import ReturnBuild
from app.modules.filing.gstr1 import Amounts, build_sections
from app.modules.filing.periods import ReturnInstance

from .test_gstr1_sections import CN, INV, SOAP, TEA, WB, A, line
from .test_gstr1_sections import PART_A as LINES

D = Decimal
SELLER = "19AAACX1111A1Z2"
GOLDEN = Path(__file__).parent / "golden" / "gstr1_part_a.json"


def inst(form="GSTR1", start=date(2026, 10, 1), end=date(2026, 10, 31)):
    return ReturnInstance(uuid.UUID(int=1), SELLER, form, "2026-10", start, end, None, "open")


def build_of(lines, instance=None):
    instance = instance or inst()
    s = build_sections(lines, kind=instance.form)
    return ReturnBuild(instance=instance, sections=s, liability=Amounts(), hsn_total=Amounts(), gap=Amounts(),
                       members=(), line_items=0, fingerprint="a" * 64, refdata_as_of={}, ca_flags=(),
                       debit_notes=0, draft=True, lines=tuple(lines))  # fmt: skip


def render(lines=LINES, options=rj.Options(), instance=None) -> bytes:
    return rj.render_json(em.export_model(build_of(lines, instance)), options)


def doc(**kw):
    return json.loads(render(**kw))


# -- the file as a whole -----------------------------------------------------------------------------------------


def test_the_part_a_file_is_the_golden_file_byte_for_byte():
    # The b2b, b2cs and hsn parts follow the one real tool file. The b2cl, cdnr and cdnur parts are our best recollection
    # of the GSTN names, unverified: if a tool sample or the test upload says otherwise, this golden file changes.
    assert render() == GOLDEN.read_bytes()


def test_the_same_return_gives_the_same_bytes_whatever_the_order_of_its_lines():
    shuffled = list(LINES)
    random.Random(7).shuffle(shuffled)
    assert render(shuffled) == render(LINES)


def test_top_level_keys_are_in_the_tools_order_and_the_file_is_minified_ascii():
    raw = render()
    assert list(json.loads(raw)) == ["gstin", "fp", "filing_typ", "gt", "cur_gt", "b2b", "b2cl", "b2cs", "cdnr",
                                     "cdnur", "hsn"]  # fmt: skip
    assert b" " not in raw.replace(b"INV/26-27", b"") and b"\n" not in raw and raw.isascii()
    d = json.loads(raw)
    assert (d["gstin"], d["fp"], d["filing_typ"], d["gt"], d["cur_gt"]) == (SELLER, "102026", "M", 0, 0)


def test_a_table_with_no_rows_is_left_out_not_written_empty():
    only_b2cs = [ln for ln in LINES if ln.supply_class == "B2CS" and ln.doc_kind == "invoice"]
    d = doc(lines=only_b2cs)
    assert set(d) == {"gstin", "fp", "filing_typ", "gt", "cur_gt", "b2cs", "hsn"}
    assert set(d["hsn"]) == {"flag", "hsn_b2c"}  # no hsn_b2b either
    assert set(doc(lines=[])) == {"gstin", "fp", "filing_typ", "gt", "cur_gt"}


# -- each table, against the examples' figures ---------------------------------------------------------------------


def test_b2b_groups_invoices_by_recipient_with_one_item_per_rate_and_a_tax_key_only_when_not_zero():
    b2b = doc()["b2b"]
    assert [p["ctin"] for p in b2b] == ["19AAACX2222B1ZU", "29AAACX3333C1ZL"] and {p["cfs"] for p in b2b} == {"N"}
    inv = b2b[0]["inv"][0]
    assert (inv["inum"], inv["idt"], inv["val"], inv["pos"], inv["inv_typ"], inv["rchrg"]) == (
        "INV/26-27/0001", "01-10-2026", 14300, "19", "R", "N")  # fmt: skip
    assert (inv["flag"], inv["updby"], inv["cflag"]) == ("U", "S", "N") and "chksum" not in inv
    assert inv["itms"] == [
        {"num": 1, "itm_det": {"samt": 200, "rt": 5, "txval": 8000, "camt": 200}},
        {"num": 2, "itm_det": {"samt": 450, "rt": 18, "txval": 5000, "camt": 450}},
    ]  # intra-state: camt and samt, no iamt
    assert b2b[1]["inv"][0]["itms"] == [{"num": 1, "itm_det": {"rt": 18, "txval": 10000, "iamt": 1800}}]


def test_b2cs_rows_are_one_per_place_and_rate_with_all_four_tax_keys_and_the_supply_type():
    rows = doc()["b2cs"]
    assert [(r["pos"], r["rt"], r["txval"], r["sply_ty"]) for r in rows] == [
        ("19", 5, 3200, "INTRA"), ("19", 18, 200000, "INTRA"), ("24", 18, 84745.76, "INTER"), ("29", 5, 2000, "INTER")]  # fmt: skip
    for r in rows:
        assert list(r) == ["samt", "csamt", "rt", "flag", "pos", "txval", "typ", "camt", "iamt", "sply_ty"]
        assert r["typ"] == "OE" and r["flag"] == "N"
    assert (rows[0]["camt"], rows[0]["samt"], rows[0]["iamt"]) == (80, 80, 0)  # the credit note is netted: 4000 - 800
    assert (rows[2]["iamt"], rows[2]["camt"]) == (15254.24, 0)


def test_hsn_is_split_b2b_and_b2c_nets_the_notes_and_writes_tax_keys_only_when_not_zero():
    hsn = doc()["hsn"]
    assert hsn["flag"] == "N" and [r["num"] for r in hsn["hsn_b2b"]] == [1, 2]
    soap_b2b = hsn["hsn_b2b"][1]
    assert (soap_b2b["hsn_sc"], soap_b2b["uqc"], soap_b2b["qty"], soap_b2b["txval"]) == ("3401", "NOS", 290, 14500)
    assert soap_b2b["iamt"] == 1800 and soap_b2b["camt"] == soap_b2b["samt"] == 405
    tea_b2b = hsn["hsn_b2b"][0]
    assert set(tea_b2b) == {"num", "hsn_sc", "uqc", "qty", "rt", "txval", "samt", "camt"}  # no iamt, no csamt
    assert all("desc" not in r for r in hsn["hsn_b2b"] + hsn["hsn_b2c"])


def test_the_hsn_total_agrees_with_the_tables_above_it():
    d = doc()
    hsn_total = sum(Decimal(str(r["txval"])) for k in ("hsn_b2b", "hsn_b2c") for r in d["hsn"][k])
    notes = sum(Decimal(str(n["itms"][0]["itm_det"]["txval"])) for p in d["cdnr"] for n in p["nt"]) + sum(
        Decimal(str(n["itms"][0]["itm_det"]["txval"])) for n in d["cdnur"]
    )
    inv = sum(Decimal(str(i["itm_det"]["txval"])) for p in d["b2b"] for v in p["inv"] for i in v["itms"])
    inv += sum(Decimal(str(i["itm_det"]["txval"])) for g in d["b2cl"] for v in g["inv"] for i in v["itms"])
    inv += sum(Decimal(str(r["txval"])) for r in d["b2cs"])
    assert hsn_total == inv - notes  # Table 12 is net of notes, so is the sum of the other tables once notes come off


def test_credit_notes_are_written_positive_with_their_own_keys():
    d = doc()
    nt = d["cdnr"][0]["nt"][0]
    assert (nt["ntty"], nt["nt_num"], nt["nt_dt"], nt["val"], nt["pos"], nt["rchrg"], nt["inv_typ"]) == (
        "C", "CN/26-27/0001", "15-10-2026", 590, "19", "N", "R")  # fmt: skip
    ur = d["cdnur"][0]
    assert (ur["typ"], ur["ntty"], ur["nt_num"], ur["val"], ur["pos"]) == ("B2CL", "C", "CN/26-27/0002", 11800, "24")
    assert d["b2cl"][0]["pos"] == "24" and d["b2cl"][0]["inv"][0]["inum"] == "INV/26-27/0003"


def test_the_tables_without_a_tool_sample_are_named():
    assert rj.unverified_tables(em.export_model(build_of(LINES))) == ("b2cl", "cdnr", "cdnur")
    only_b2b = [ln for ln in LINES if ln.supply_class == "B2B" and ln.doc_kind == "invoice"]
    assert rj.unverified_tables(em.export_model(build_of(only_b2b))) == ()


# -- numbers -----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "text"),
    [("0", "0"), ("0.00", "0"), ("-0.00", "0"), ("500.00", "500"), ("99.5", "99.5"), ("99.50", "99.5"),
     ("1234.56", "1234.56"), ("0.1", "0.1"), ("1E+3", "1000"), ("1E-2", "0.01"), ("12345678901234.56", "12345678901234.56"),
     ("-18.50", "-18.5"), ("100000000000", "100000000000")],
)  # fmt: skip
def test_numbers_are_whole_or_at_most_two_decimals_never_an_exponent_never_a_float(value, text):
    assert rj.number(Decimal(value)) == text
    assert "e" not in text.lower()


@pytest.mark.parametrize("value", ["0.005", "0.004", "0.125", "1.001", "-0.005"])
def test_the_file_never_rounds_a_figure_with_more_than_two_decimals(value):
    with pytest.raises(rj.FigureError):
        rj.number(Decimal(value))


def test_a_three_place_amount_in_a_model_stops_the_render():
    lines = [replace(LINES[0], taxable_value=D("100.125"))]
    with pytest.raises(rj.FigureError):
        render(lines)


def test_rows_of_one_invoice_that_disagree_stop_the_export_and_are_never_picked_between():
    base = line("INV-9", 5, INV, "B2B", WB, SOAP, "1", "100.00", cgst="9.00", sgst="9.00", value="118.00", buyer=A)
    other = replace(base, doc_value=D("999.00"), rate=D("5"), hsn="0902", uqc="KGS")
    with pytest.raises(em.NotRenderable):
        render([base, other])


def test_a_float_is_refused_by_the_writer():
    with pytest.raises(TypeError):
        rj.dumps({"x": 1.5})


def test_hsn_quantity_is_rounded_half_up_to_two_decimals_in_the_file_only():
    lines = [
        line("INV-1", 5, INV, "B2CS", WB, SOAP, "1.125", "100.00", cgst="9.00", sgst="9.00", value="118.00"),
        line("INV-2", 6, INV, "B2CS", WB, SOAP, "2.250", "100.00", cgst="9.00", sgst="9.00", value="118.00"),
    ]
    row = doc(lines=lines)["hsn"]["hsn_b2c"][0]
    assert row["qty"] == 3.38 and build_of(lines).sections.hsn_b2c[0].quantity == D("3.375")  # 3.375 stays in the build


def test_a_negative_hsn_quantity_tie_rounds_away_from_zero_like_a_positive_one():
    net = [
        line("INV-1", 5, INV, "B2CS", WB, SOAP, "1", "100.00", cgst="9.00", sgst="9.00", value="118.00"),
        line("CN-1", 6, CN, "B2CS", WB, SOAP, "2.125", "100.00", cgst="9.00", sgst="9.00", value="118.00",
             original=("INV-1", date(2026, 10, 5))),
    ]  # fmt: skip
    assert doc(lines=net)["hsn"]["hsn_b2c"][0]["qty"] == -1.13  # -1.125 provisional (CA-3), half up away from zero


# -- options for the portal test upload ---------------------------------------------------------------------------


def test_the_placeholder_checksum_option_writes_a_wrong_checksum_on_every_row_that_carries_one():
    d = doc(options=rj.Options(chksum="placeholder"))
    assert d["b2b"][0]["inv"][0]["chksum"] == "0" * 64 and d["b2cs"][0]["chksum"] == "0" * 64
    assert d["hsn"]["chksum"] == "0" * 64 and "chksum" not in doc()["b2b"][0]["inv"][0]


def test_turning_the_system_flags_off_removes_them_all():
    raw = render(options=rj.Options(flags=False)).decode()
    for key in ('"flag"', '"cflag"', '"cfs"', '"updby"'):
        assert key not in raw
    assert '"inv_typ"' in raw and '"rchrg"' in raw  # these are data, not system flags


def test_the_generation_date_is_written_only_when_asked_for_and_last():
    assert "fil_dt" not in doc()
    d = doc(options=rj.Options(fil_dt=date(2026, 11, 20)))
    assert list(d)[-1] == "fil_dt" and d["fil_dt"] == "20-11-2026"


# -- what is not rendered ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "instance",
    [inst("IFF"), inst(start=date(2026, 10, 1), end=date(2026, 12, 31))],
    ids=["an IFF", "a quarterly GSTR-1"],
)
def test_an_iff_and_a_quarterly_return_are_not_rendered_with_a_plain_reason(instance):
    with pytest.raises(em.NotRenderable) as e:
        em.export_model(build_of([], instance))
    assert str(e.value).endswith(".") and "available" in str(e.value)


def test_the_tables_left_out_of_the_file_are_named_for_the_screen():
    assert len(em.NOT_IN_FILE) == 1 and "Table 14" in em.NOT_IN_FILE[0]  # Table 13 is in the file now


def test_an_invoice_value_and_place_come_from_its_first_row_and_two_notes_do_not_merge():
    lines = [
        line("CN-1", 5, CN, "CDNR", WB, SOAP, "1", "100.00", cgst="9.00", sgst="9.00", value="118.00", buyer=A,
             original=("INV-1", date(2026, 10, 1))),
        line("CN-2", 5, CN, "CDNR", WB, TEA, "1", "50.00", cgst="1.25", sgst="1.25", value="52.50", buyer=A,
             original=("INV-1", date(2026, 10, 1))),
    ]  # fmt: skip
    notes = doc(lines=lines)["cdnr"][0]["nt"]
    assert [(n["nt_num"], n["val"]) for n in notes] == [("CN-1", 118), ("CN-2", 52.5)]


def test_a_line_replaced_by_another_changes_the_file(monkeypatch):
    base = render()
    changed = [replace(LINES[0], taxable_value=LINES[0].taxable_value + 1)] + list(LINES[1:])
    assert render(changed) != base
