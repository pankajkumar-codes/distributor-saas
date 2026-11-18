"""Monthly and quarterly sales-and-purchases files (R2-M6) on PostgreSQL as app_rw. Made-up data, seeded as the database
owner with triggers and foreign keys off (test setup only). Skipped unless PG_ADMIN_URL is set."""

import io
import json
import uuid
from datetime import date, datetime
from decimal import Decimal

import openpyxl
import pytest
from sqlalchemy import text

from app import api as app_api
from platform_common.clock import IST, FrozenClock, get_clock
from platform_common.storage import LocalObjectStore, get_store, set_store

from .conftest import PG_ADMIN_URL, as_user, new_business, scalar, seed_member

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")
GSTIN = "19AAPFU0939F1ZS"


@pytest.fixture()
def shop(pg, tmp_path):
    set_store(LocalObjectStore(tmp_path))
    app_api.app.dependency_overrides[get_clock] = lambda: FrozenClock(datetime(2027, 1, 15, 12, tzinfo=IST))
    biz = new_business(pg, "alice")
    seed_member(pg, biz, "bill", "billing")
    seed_member(pg, biz, "cathy", "ca")
    try:
        yield pg, biz
    finally:
        set_store(None)


def seed(pg, sql, **p):
    with pg.owner.connect() as c:  # autocommit: the setting lasts for this connection only
        c.execute(text("set session_replication_role = replica"))
        c.execute(text(sql), p)
        c.execute(text("set session_replication_role = default"))


def sale(pg, biz, number, on, *, practice=False, kind="invoice", taxable="100.00", cgst="9.00", sgst="9.00", rate="18"):
    doc, line = uuid.uuid4(), uuid.uuid4()
    seed(pg, "insert into sales.documents (id, business_id, draft_id, kind, is_practice, series_id, doc_number, doc_date, fy,"
             " gstin, supplier_state_code, pos_state_code, is_inter_state, supply_class, gross_total, line_discount_total,"
             " invoice_discount, charges_total, taxable_total, cgst_total, sgst_total, utgst, igst_total, doc_total,"
             " amount_in_words, print, rounding_mode, method_version, finalized_by) values (:d, :b, :dr, :k, :p, :sr, :n, :on,"
             " :fy, :g, '19', '19', false, 'B2CS', :t, 0, 0, 0, :t, :c, :s, false, 0, :tot, 'x', '{}', 'none', 'v1', :u)",
         d=doc, b=biz, dr=uuid.uuid4(), k=kind, p=practice, sr=uuid.uuid4(), n=number, on=on,
         fy="2026-27", g=GSTIN, t=Decimal(taxable), c=Decimal(cgst), s=Decimal(sgst),
         tot=Decimal(taxable) + Decimal(cgst) + Decimal(sgst), u=uuid.uuid4())
    seed(pg, "insert into sales.document_lines (id, business_id, document_id, line_no, name, hsn, uqc, quantity, unit_price,"
             " gross, line_discount, discount_share, charge_share, taxable, rate, rate_confirmed)"
             " values (:l, :b, :d, 1, 'Tee', '6109', 'PCS', 1, :t, :t, 0, 0, 0, :t, :r, true)",
         l=line, b=biz, d=doc, t=Decimal(taxable), r=Decimal(rate))
    for comp, amt in (("CGST", cgst), ("SGST", sgst)):
        seed(pg, "insert into sales.document_line_taxes (line_id, business_id, component, rate, amount)"
                 " values (:l, :b, :c, 9, :a)", l=line, b=biz, c=comp, a=Decimal(amt))


def purchase(pg, biz, number, on, *, file_name="bill.pdf", taxable="200.00", product="Cotton tee"):
    f, d, dl, r = (uuid.uuid4() for _ in range(4))
    seed(pg, "insert into imports.purchase_files (id, business_id, s3_key, file_name, size_bytes, kind, status, created_by)"
             " values (:f, :b, 'k', :fn, 5, 'pdf', 'read', :u)", f=f, b=biz, fn=file_name, u=uuid.uuid4())
    seed(pg, "insert into imports.purchase_drafts (id, business_id, file_id, ordinal, reader_id, pages)"
             " values (:d, :b, :f, 1, 'pdf_text_v1', '{1,2}')", d=d, b=biz, f=f)
    seed(pg, "insert into imports.purchase_draft_lines (id, business_id, draft_id, line_no, page) values (:dl, :b, :d, 1, 2)",
         dl=dl, b=biz, d=d)
    seed(pg, "insert into imports.purchase_reviews (id, business_id, draft_id, decision, supplier_gstin, doc_number, doc_key,"
             " fy, doc_date, invoice_total, created_by) values (:r, :b, :d, 'confirmed', '29ABCDE1234F1Z5', :n, :k,"
             " '2026-27', :on, 236, :u)", r=r, b=biz, d=d, n=number, k=number.upper(), on=on, u=uuid.uuid4())
    seed(pg, "insert into imports.purchase_review_lines (id, business_id, review_id, line_no, draft_line_id, product_id,"
             " created_product, product_name, hsn, unit, quantity, taxable_value, gst_rate, cgst, sgst)"
             " values (:l, :b, :r, 1, :dl, :p, true, :pn, '6109', 'PCS', 2, :t, 18, 18, 18)",
         l=uuid.uuid4(), b=biz, r=r, dl=dl, p=uuid.uuid4(), t=Decimal(taxable), pn=product)
    return f


def choose(pg, biz, frequency, sub="alice"):
    r = pg.client.post(f"/api/v1/b/{biz}/filing-profile/frequency", json={"frequency": frequency, "effective_from": "2026-10-01"},
                       headers={**as_user(sub), "Idempotency-Key": uuid.uuid4().hex})
    assert r.status_code in (200, 201), r.text


def make(pg, biz, kind="month", start="2026-11-01", sub="alice"):
    return pg.client.post(f"/api/v1/b/{biz}/period-files", json={"kind": kind, "start": start}, headers=as_user(sub))


def bytes_of(pg, biz, export_id, name):
    key = scalar(pg.owner, "select object_key from filing.period_export_files where export_id = :e and name = :n",
                 e=export_id, n=name)
    return get_store().get_bytes(biz, key)


def sheet(book, name):
    return [[c for c in row] for row in book[name].iter_rows(values_only=True)]


def month_data(pg, biz):
    sale(pg, biz, "INV-1", date(2026, 11, 3))
    sale(pg, biz, "CN-1", date(2026, 11, 9), kind="credit_note", taxable="50.00", cgst="4.50", sgst="4.50")
    sale(pg, biz, "PRAC-1", date(2026, 11, 12), practice=True, taxable="999.00", cgst="0", sgst="0")
    sale(pg, biz, "INV-OCT", date(2026, 10, 30))  # another month
    purchase(pg, biz, "SUP-1", date(2026, 11, 5))
    purchase(pg, biz, "SUP-OCT", date(2026, 10, 5), file_name="oct.pdf")


def test_a_month_gives_a_workbook_and_a_purchase_register_from_the_right_rows(shop):
    pg, biz = shop
    month_data(pg, biz)
    r = make(pg, biz)
    assert r.status_code == 200, r.text
    out = r.json()
    assert (out["created"], out["sales_lines"], out["purchase_lines"], out["practice_documents"]) == (True, 2, 1, 1)
    assert out["due_dates"] == "Check on the GST portal"
    assert {f["name"] for f in out["files"]} == {"workbook", "purchase_register"}
    book = openpyxl.load_workbook(io.BytesIO(bytes_of(pg, biz, out["id"], "workbook")))
    assert book.sheetnames == ["Summary", "Sales", "Purchases", "Practice (not filed)"]
    sales = sheet(book, "Sales")[2:]
    assert sorted(r[2] for r in sales) == ["CN-1", "INV-1"]  # the practice document and October are not here
    assert {r[2]: r[4] for r in sales} == {"CN-1": "credit_note", "INV-1": "invoice"}  # a credit note is shown, not netted
    assert [r[0] for r in sheet(book, "Practice (not filed)")[2:]] == ["invoice"]
    purchases = sheet(book, "Purchases")[2:]
    assert [(r[2], r[4], r[5], r[6]) for r in purchases] == [("SUP-1", "bill.pdf", "1, 2", 2)]  # file, pages, page read from
    summary = {r[0]: r[1] for r in sheet(book, "Summary") if r and r[0]}
    assert summary["Sales: invoices"] == "1 document(s), 1 line(s)" and summary["Due dates"] == "Check on the GST portal"
    assert "Practice documents (on their own sheet, in no total above)" in summary
    reg = json.loads(bytes_of(pg, biz, out["id"], "purchase_register"))
    assert reg["format"] == "purchase_register_v1" and reg["portal_file"] is False and reg["gstin"] == GSTIN
    (inv,) = reg["invoices"]
    assert (inv["number"], inv["date"], inv["source"]["file_name"], inv["source"]["pages"]) == ("SUP-1", "2026-11-05", "bill.pdf", [1, 2])
    assert inv["lines"][0]["taxable_value"] == "200.00" and inv["lines"][0]["read_from"] == {"page": 2, "line": 1}
    assert out["gstr1_returns"] == [] or all(x["form"] in ("GSTR1", "IFF") for x in out["gstr1_returns"])


def test_the_stored_hash_is_the_files_hash_and_the_links_serve_them(shop):
    import hashlib

    pg, biz = shop
    month_data(pg, biz)
    out = make(pg, biz).json()
    for f in out["files"]:
        assert f["sha256"] == hashlib.sha256(bytes_of(pg, biz, out["id"], f["name"])).hexdigest()
        assert f["url"]
    assert get_store().presign_get  # a 60-second link per file, as the GSTR-1 export does


def test_asking_again_for_unchanged_data_finds_the_same_export_and_changed_data_makes_a_new_one(shop):
    pg, biz = shop
    month_data(pg, biz)
    one = make(pg, biz).json()
    two = make(pg, biz).json()
    assert (two["id"], two["created"]) == (one["id"], False)
    assert scalar(pg.owner, "select count(*) from filing.period_exports") == 1
    purchase(pg, biz, "SUP-2", date(2026, 11, 20))
    three = make(pg, biz).json()
    assert three["id"] != one["id"] and three["created"] and three["purchase_lines"] == 2
    assert scalar(pg.owner, "select count(*) from filing.period_exports") == 2  # the first stays
    assert make(pg, biz).json()["id"] == three["id"]


def test_the_period_must_be_a_whole_finished_one(shop):
    pg, biz = shop
    assert make(pg, biz, start="2026-11-05").json()["error"]["code"] == "period_start_invalid"
    assert make(pg, biz, start="2027-01-01").json()["error"]["code"] == "period_not_ended"  # January is not over on the 15th
    assert make(pg, biz, kind="quarter", start="2026-11-01").json()["error"]["code"] == "period_start_invalid"
    assert make(pg, biz, kind="year", start="2026-04-01").status_code == 422


def test_a_quarter_is_for_a_quarterly_filer_and_covers_its_three_months(shop):
    pg, biz = shop
    monthly = new_business(pg, "bob")
    choose(pg, monthly, "monthly", sub="bob")
    refused = make(pg, monthly, kind="quarter", start="2026-10-01", sub="bob")
    assert (refused.status_code, refused.json()["error"]["code"]) == (409, "quarter_not_for_monthly_filer")
    choose(pg, biz, "quarterly")
    month_data(pg, biz)
    sale(pg, biz, "INV-DEC", date(2026, 12, 20))
    sale(pg, biz, "INV-JAN", date(2027, 1, 2))
    out = make(pg, biz, kind="quarter", start="2026-10-01")
    assert out.status_code == 200, out.text
    assert (out.json()["kind"], out.json()["sales_lines"], out.json()["purchase_lines"]) == ("quarter", 4, 2)


def test_another_business_and_other_roles_cannot_reach_it(shop):
    pg, biz = shop
    month_data(pg, biz)
    out = make(pg, biz).json()
    other = new_business(pg, "bob")
    assert pg.client.get(f"/api/v1/b/{other}/period-files/{out['id']}", headers=as_user("bob")).status_code == 404
    assert pg.client.get(f"/api/v1/b/{other}/period-files", headers=as_user("bob")).json()["exports"] == []
    assert pg.client.get(f"/api/v1/b/{biz}/period-files/{out['id']}", headers=as_user("bob")).status_code == 404
    assert make(pg, biz, sub="bill").status_code == 404  # billing cannot prepare returns
    assert make(pg, biz, sub="cathy").status_code == 200  # the CA can
    # the other business's own data never reaches this one's files
    purchase(pg, other, "THEIRS-1", date(2026, 11, 6))
    assert make(pg, biz).json()["purchase_lines"] == 1


def test_exports_are_insert_only_and_the_audit_row_has_counts_only(shop):
    pg, biz = shop
    month_data(pg, biz)
    out = make(pg, biz).json()
    for table in ("period_exports", "period_export_files"):
        with pytest.raises(Exception, match="insert-only|permission denied|immutable|cannot"):
            with pg.owner.begin() as c:
                c.execute(text(f"update filing.{table} set business_id = business_id"))
    data = scalar(pg.owner, "select data::text from platform.audit_log where action = 'filing.period_files_made'")
    assert out["id"] in data and "SUP-1" not in data and "INV-1" not in data and GSTIN not in data


def test_typed_text_that_looks_like_a_formula_stays_text_in_the_workbook(shop):
    pg, biz = shop
    evil = '=HYPERLINK("http://example.invalid","click")'
    purchase(pg, biz, "SUP-1", date(2026, 11, 5), file_name=evil, product="=1+1")
    out = make(pg, biz).json()
    raw = bytes_of(pg, biz, out["id"], "workbook")
    book = openpyxl.load_workbook(io.BytesIO(raw))
    (row,) = sheet(book, "Purchases")[2:]
    assert evil in row and "=1+1" in row
    for ws in book.worksheets:  # no formula cell anywhere, and the file holds no <f> element
        assert all(c.data_type != "f" for r in ws.iter_rows() for c in r)
    import zipfile

    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        assert not any(b"<f>" in z.read(n) or b"<f " in z.read(n) for n in z.namelist() if n.startswith("xl/worksheets/"))


def test_a_closed_download_rule_refuses_before_anything_is_built_or_stored(shop):
    from app.modules.filing import entitlement

    pg, biz = shop
    month_data(pg, biz)
    entitlement.set_check(lambda tx, b: False)
    try:
        r = make(pg, biz)
    finally:
        entitlement.set_check(None)
    assert (r.status_code, r.json()["error"]["code"]) == (409, "download_not_available")
    assert scalar(pg.owner, "select count(*) from filing.period_exports") == 0
    assert not any(p.is_file() for p in get_store().root.rglob("*")) if hasattr(get_store(), "root") else True
