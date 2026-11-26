"""R1-M7 slice 3: the supply-line view and build_return over confirmed uploaded invoices, on PostgreSQL through the
real reader and confirm. Skipped unless PG_ADMIN_URL is set."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.filing.interface import build_return, ensure_instances, instances_between

from .conftest import PG_ADMIN_URL, ctx, new_business, scalar, user_id
from .test_confirm_postgres import OCT, XLSX, confirm, line, month, monthly, real_readers, stage  # noqa: F401
from .test_parse_postgres import GSTIN
from .test_uploads_postgres import get, post, run_jobs, shop, upload  # noqa: F401

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")

CONTRACT_V1 = [
    "source_kind", "source_id", "source_ref", "gstin", "return_instance_id", "return_period", "doc_date",
    "doc_number", "doc_kind", "supply_class", "counterparty_gstin", "counterparty_name", "pos_state_code", "rate",
    "hsn", "uqc", "quantity", "taxable_value", "igst", "cgst", "sgst", "cess", "operator_gstin", "marketplace",
    "original_doc_number", "original_doc_date", "doc_value", "business_id",
]  # fmt: skip


def built(shop, sub="alice", period=date(2026, 10, 1)):  # noqa: F811
    pg, biz, _ = shop
    with pg.app_rw.begin() as c:
        ctx(c, user_id(pg.owner, sub), biz)
        tx = Session(bind=c)
        inst = [i for i in instances_between(tx, GSTIN, period, date(2026, 10, 31)) if i.form == "GSTR1"][0]
        return build_return(tx, inst)


def test_the_view_contract_v1_is_exactly_the_agreed_columns(shop):  # noqa: F811
    pg, _, _ = shop
    cols = [r[0] for r in pg.owner.connect().execute(text(
        "select column_name from information_schema.columns where table_schema = 'filing'"
        " and table_name = 'v_supply_lines' order by ordinal_position"))]
    assert cols == CONTRACT_V1


def test_a_months_uploaded_invoices_build_into_sections_that_reconcile(shop):  # noqa: F811
    monthly(shop)
    assert confirm(shop, stage(shop, month(shop))).status_code == 200
    b = built(shop)
    assert b.draft and b.instance.form == "GSTR1"
    assert [r.invoice_number for r in b.sections.b2b] == ["INV-3"]
    assert all(r.startswith("a.xlsx row ") for r in b.sections.b2b[0].source_refs)
    assert b.liability.taxable_value == Decimal("850")  # 200 + 100 + 200 + 200 - 50 (CN-1) + 200 (DN-1, #462)
    assert b.liability.igst == Decimal("36")
    assert b.gap.is_zero()  # Table 12 agrees with the liability tables
    assert all(r.source_refs for r in (*b.sections.b2cs, *b.sections.hsn_b2c, *b.sections.hsn_b2b))
    assert b.line_items == b.sections.line_items > 0


def test_an_uploaded_debit_note_is_in_the_return_and_an_older_one_is_still_counted_out(shop):  # noqa: F811
    """#462: a debit note confirmed now is a supply line (here netted into B2CS, adding, and in Table 12). One
    confirmed before #462 has no class and no return; the return keeps saying it is not included."""
    pg, _, _ = shop
    monthly(shop)
    assert confirm(shop, stage(shop, month(shop))).status_code == 200
    b = built(shop)
    assert b.debit_notes == 0 and "debit_notes_unsummed" not in {f.code for f in b.ca_flags}
    assert any(m.startswith("DN-1|own_debit_note|") for m in b.members) and b.gap.is_zero()
    assert {"marketplace_reports", "uqc_mapping", "exports_sez_rcm"} <= {f.code for f in b.ca_flags}
    with pg.owner.connect() as c:  # what a debit note confirmed before #462 looks like (the owner engine autocommits)
        c.execute(text("set session_replication_role = replica"))  # skip the insert-only guard, test setup only
        c.execute(text("update imports.documents set supply_class = null, return_instance_id = null, return_period = null"
                       " where doc_number = 'DN-1'"))
        c.execute(text("set session_replication_role = default"))
    old = built(shop)
    assert old.debit_notes == 1 and "debit_notes_unsummed" in {f.code for f in old.ca_flags}
    assert old.liability.taxable_value == b.liability.taxable_value - Decimal("200")


def test_the_fingerprint_is_stable_between_builds(shop):  # noqa: F811
    monthly(shop)
    assert confirm(shop, stage(shop, month(shop))).status_code == 200
    a, b = built(shop), built(shop)
    assert a.fingerprint == b.fingerprint and len(a.fingerprint) == 64


def test_a_month_with_nothing_confirmed_builds_empty(shop):  # noqa: F811
    pg, biz, _ = shop
    monthly(shop)
    with pg.app_rw.begin() as c:
        ctx(c, user_id(pg.owner, "alice"), biz)
        tx = Session(bind=c)
        inst = [i for i in ensure_instances(tx, GSTIN, date(2026, 10, 5)) if i.form == "GSTR1"][0]
        b = build_return(tx, inst)
    assert b.line_items == 0 and b.liability.is_zero() and b.members == () and b.debit_notes == 0


def test_the_view_shows_a_tenant_only_its_own_lines(shop):  # noqa: F811
    pg, biz, _ = shop
    monthly(shop)
    assert confirm(shop, stage(shop, month(shop))).status_code == 200
    other = new_business(pg, "mallory")
    with pg.app_rw.begin() as c:
        ctx(c, user_id(pg.owner, "mallory"), other)
        assert c.execute(text("select count(*) from filing.v_supply_lines")).scalar() == 0
        assert c.execute(text("select count(*) from imports.v_unsummed_documents")).scalar() == 0
    with pg.app_rw.begin() as c:
        ctx(c, user_id(pg.owner, "alice"), biz)
        assert c.execute(text("select count(*) from filing.v_supply_lines")).scalar() == 6  # the debit note too (#462)


def test_two_confirms_of_one_invoice_at_once_import_it_once(shop):  # noqa: F811
    pg, biz, _ = shop
    monthly(shop)
    run_a = stage(shop, [line("INV-1"), line("INV-8")], "a.xlsx")
    run_b = stage(shop, [line("INV-1"), line("INV-9")], "b.xlsx")
    with ThreadPoolExecutor(2) as ex:
        outs = list(ex.map(lambda r: confirm(shop, r), (run_a, run_b)))
    assert all(o.status_code in (200, 409) for o in outs), [o.text for o in outs]
    assert scalar(pg.owner, "select count(*) from imports.documents where doc_number = 'INV-1'") == 1
    assert scalar(pg.owner, "select count(*) from imports.document_lines l join imports.documents d"
                  " on d.id = l.document_id where d.doc_number = 'INV-1'") == 1
    b = built(shop)
    assert b.liability.taxable_value >= Decimal("200") and sum(m.startswith("INV-1|") for m in b.members) == 1


def test_the_same_invoice_in_a_second_file_is_not_counted_twice(shop):  # noqa: F811
    """What a PDF of an invoice already uploaded as Excel must also do once PDF confirm is enabled."""
    monthly(shop)
    assert confirm(shop, stage(shop, [line("INV-1")], "excel.xlsx")).status_code == 200
    first = built(shop).liability.taxable_value
    out = confirm(shop, stage(shop, [line("INV-1"), line("INV-2")], "again.xlsx"))
    assert out.status_code == 200
    assert built(shop).liability.taxable_value == first + Decimal("200")  # INV-2 only


def test_a_qrmp_quarter_adds_its_iff_month_to_table_12_and_still_reconciles(shop):  # noqa: F811
    pg, biz, _ = shop
    r = post(pg, f"/api/v1/b/{biz}/filing-profile/frequency", {"frequency": "quarterly", "effective_from": "2026-10-01"},
             key=uuid.uuid4().hex)
    assert r.status_code in (200, 201), r.text
    rows = [line("INV-1"), line("INV-3", buyer="29DEMOC9999C1Z1"),
            line("DN-1", kind="Debit note", original="INV-1", original_date=OCT)]
    assert confirm(shop, stage(shop, rows)).status_code == 200
    with pg.app_rw.begin() as c:
        ctx(c, user_id(pg.owner, "alice"), biz)
        tx = Session(bind=c)
        insts = instances_between(tx, GSTIN, date(2026, 10, 1), date(2026, 12, 31))
        iff = [i for i in insts if i.form == "IFF"][0]
        quarter = [i for i in insts if i.form == "GSTR1"][0]
        qb, ib = build_return(tx, quarter), build_return(tx, iff)
    assert [r.invoice_number for r in ib.sections.b2b] == ["INV-3"] and ib.sections.hsn_b2b == ()
    assert qb.sections.b2b == () and len(qb.sections.hsn_b2b) == 1  # Table 12 covers the IFF month
    # #462: the debit note to a consumer is netted into B2CS, which an IFF does not carry, so the quarter holds it
    assert qb.liability.taxable_value == Decimal("600") and qb.gap.is_zero()
    assert ib.debit_notes == 0 and qb.debit_notes == 0
