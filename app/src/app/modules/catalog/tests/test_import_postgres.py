"""Product CSV import functions on PostgreSQL, as app_rw with FORCE row-level security
(LLD-3 §7, AC3-12, AC3-13, AC3-14, AC3-21, AC3-22 at function level; the routes and jobs
are S3-c2). Every file is made up in the test: no real catalogue. Skipped unless
PG_ADMIN_URL is set.
"""

import concurrent.futures
import io
import time
import uuid
from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import api as app_api
from platform_common import storage
from platform_common.clock import IST, FrozenClock, get_clock
from platform_common.errors import Conflict, Deny, Invalid
from platform_common.uow import Principal

from .. import product_import as imp
from .conftest import PG_ADMIN_URL, as_user, ctx, new_business, user_id

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")

TODAY = date(2026, 10, 27)
HEADER = "code,name,hsn,unit,sale_rate,gst_rate,gst_rate_valid_from,barcode,tax_category,has_cess"


@pytest.fixture()
def shop(pg):
    app_api.app.dependency_overrides[get_clock] = lambda: FrozenClock(datetime(2026, 10, 27, 12, tzinfo=IST))
    biz = new_business(pg, "alice")
    return pg, biz, user_id(pg.owner, "alice")


def run_in(shop, fn):
    """One unit of work as alice, committed: what a job or route would do."""
    pg, biz, alice = shop
    with Session(pg.app_rw) as tx, tx.begin():
        ctx(tx, alice, biz)
        uow = type("U", (), {})()
        uow.tx = tx
        uow.principal = Principal(user_sub="alice", request_id="test", user_id=alice, business_id=biz, role="owner")
        return fn(uow)


def csv_file(*lines: str) -> bytes:
    return ("\n".join((HEADER, *lines)) + "\n").encode()


def upload(shop, content: bytes, name="products.csv"):
    run = run_in(shop, lambda u: imp.start(u, name, len(content), TODAY))
    return run_in(shop, lambda u: imp.parse(u, run.id, content, TODAY))


def preview(shop, run_id, status=None):
    found, _ = run_in(shop, lambda u: imp.rows(u, run_id, status, 500, 0))
    return found


def products(shop):
    pg, biz, _ = shop
    with pg.owner.connect() as c:
        return {r.code: r for r in c.execute(text(
            "select code, name, sale_rate, status, version, source_import_row_id from catalog.products"
            " where business_id = :b and status <> 'deleted'"), {"b": biz})}


def rates(shop, code):
    pg, biz, _ = shop
    with pg.owner.connect() as c:
        return [tuple(r) for r in c.execute(text(
            "select r.rate, r.valid_from, r.source, exists (select 1 from catalog.product_rate_confirmations x"
            " where x.rate_id = r.id) from catalog.product_rates r join catalog.products p on p.id = r.product_id"
            " where p.business_id = :b and p.code = :c order by r.valid_from"), {"b": biz, "c": code})]


SOAP = "SOAP-1,Neem soap 100 g,3401,PCS,45.50,18,01-04-2026,8901234567890,taxable,no"
OIL = "OIL-1,Coconut oil 500 ml,1513,BTL,120,5,2026-04-01,,taxable,"
RICE = "RICE-1,Loose rice,1006,KGS,60,,,,exempt,"


def test_the_template_route_serves_the_header_row(shop):
    pg, biz, _ = shop
    r = pg.client.get(f"/api/v1/b/{biz}/products/import-template", headers=as_user("alice"))
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert r.text.strip() == HEADER
    assert imp.template_csv().decode().strip() == HEADER


def test_a_clean_file_previews_then_applies_new_products(shop):  # AC3-13, AC3-14
    run = upload(shop, csv_file(SOAP, OIL, RICE))
    assert (run.status, run.counts) == ("preview", {"new": 3, "changed": 0, "unchanged": 0, "invalid": 0,
                                                     "conflict": 0})
    assert products(shop) == {}  # nothing is saved before confirm
    assert run.s3_key == storage.key_for(shop[1], "uploads", run.id)  # area-first (#58)
    done = run_in(shop, lambda u: imp.apply(u, run.id, apply_changes=True, today=TODAY))
    assert done.status == "applied" and done.counts["applied"] == 3
    saved = products(shop)
    assert saved["SOAP-1"].sale_rate == Decimal("45.50") and saved["RICE-1"].status == "active"
    assert all(p.source_import_row_id is not None for p in saved.values())  # traceable to the file row
    # Imported rates are unconfirmed and marked as from the file; the exempt product has none.
    assert rates(shop, "SOAP-1") == [(Decimal("18.00"), date(2026, 4, 1), "csv_import", False)]
    assert rates(shop, "RICE-1") == []
    pg, biz, _ = shop
    with pg.owner.connect() as c:
        data = c.execute(text("select data from platform.audit_log where business_id = :b"
                              " and action = 'catalog.import_applied'"), {"b": biz}).scalar_one()
    assert data["counts"]["applied"] == 3


def test_the_same_file_twice_is_already_imported(shop):  # AC3-12, AC3-21
    content = csv_file(SOAP)
    first = upload(shop, content)
    run_in(shop, lambda u: imp.apply(u, first.id, apply_changes=True, today=TODAY))
    again = upload(shop, content, name="products (1).csv")
    assert (again.status, again.duplicate_of, again.error_code) == ("discarded", first.id, "already_imported")
    assert len(products(shop)) == 1
    with pytest.raises(Conflict) as e:
        run_in(shop, lambda u: imp.apply(u, again.id, apply_changes=True, today=TODAY))
    assert e.value.code == "import_not_ready"


def test_a_second_upload_supersedes_an_open_preview(shop):  # AC3-21
    content = csv_file(SOAP)
    first = upload(shop, content)
    second = upload(shop, content)
    assert second.status == "preview"
    old = run_in(shop, lambda u: imp.get_run(u, first.id))
    assert (old.status, old.superseded_by) == ("discarded", second.id)
    with pytest.raises(Conflict):
        run_in(shop, lambda u: imp.apply(u, first.id, apply_changes=True, today=TODAY))


def test_repeated_codes_invalid_rows_and_formulas_are_never_applied(shop):  # AC3-12
    run = upload(shop, csv_file(
        SOAP,
        "soap-1,Neem soap again,3401,PCS,40,18,01-04-2026,,taxable,no",   # same code, other case
        "BAD-1,Rate typo,3401,PCS,10,81,01-04-2026,,taxable,no",          # 81 isn't on the list
        "=HYPERLINK(\"x\"),Formula,3401,PCS,10,18,01-04-2026,,taxable,no",
        "NORATE-1,No rate given,3401,PCS,10,,,,taxable,no",                # never filled (AC3-4)
        "DATE-1,Bad date,3401,PCS,10,18,2026/04/01,,taxable,no",
        "UNIT-1,Odd unit,3401,XYZ,10,18,01-04-2026,,taxable,no",
        OIL,
    ))
    assert run.counts == {"new": 1, "changed": 0, "unchanged": 0, "invalid": 5, "conflict": 2}
    by_row = {r["row_number"]: r for r in preview(shop, run.id)}
    assert by_row[2]["status"] == by_row[3]["status"] == "conflict"
    assert by_row[2]["errors"][0]["code"] == "code_repeated"
    assert [e["code"] for e in by_row[4]["errors"]] == ["rate_not_allowed"]
    assert by_row[5]["errors"][0]["code"] == "formula"
    assert by_row[5]["parsed"]["code"].startswith("=")  # kept as text for the preview, never evaluated
    assert by_row[6]["errors"][0]["code"] == "rate_required"
    assert by_row[7]["errors"][0]["code"] == "date_invalid"
    assert by_row[8]["errors"][0]["code"] == "uqc_unknown"
    run_in(shop, lambda u: imp.apply(u, run.id, apply_changes=True, today=TODAY))
    assert set(products(shop)) == {"OIL-1"}


@pytest.mark.parametrize(
    ("header", "code"),
    [
        (HEADER.replace("unit", "units"), "header_invalid"),
        (HEADER.replace(",gst_rate_valid_from", ""), "header_invalid"),
        (HEADER + ",code", "header_invalid"),
    ],
)
def test_a_wrong_header_fails_the_whole_file(shop, header, code):
    content = (header + "\n" + SOAP + "\n").encode()
    run = upload(shop, content)
    assert (run.status, run.error_code) == ("failed", code)
    assert preview(shop, run.id) == []


def test_files_the_reader_refuses_fail_the_run(shop):
    run = upload(shop, b"\xff\xfe not utf-8")
    assert (run.status, run.error_code) == ("failed", "file_rejected")
    with pytest.raises(Invalid) as refused:  # only .csv and .xlsx get an upload at all
        run_in(shop, lambda u: imp.start(u, "products.pdf", 5, TODAY))
    assert refused.value.code == "file_type_unsupported"


def test_changed_rows_add_a_rate_row_and_apply_only_when_asked(shop):  # AC3-14
    first = upload(shop, csv_file(SOAP, OIL))
    run_in(shop, lambda u: imp.apply(u, first.id, apply_changes=True, today=TODAY))
    run = upload(shop, csv_file(
        "SOAP-1,Neem soap 100 g,3401,PCS,45.5,18,01-04-2026,8901234567890,taxable,no",  # 45.5 == 45.50
        "OIL-1,Coconut oil 500 ml,1513,BTL,125,18,2026-07-01,,taxable,",
    ))
    assert (run.counts["unchanged"], run.counts["changed"]) == (1, 1)
    changed = preview(shop, run.id, "changed")[0]
    assert {d["field"]: (d["saved"], d["file"]) for d in changed["diff"]} == {
        "sale_rate": ("120", "125"), "gst_rate": ("5", "18 from 2026-07-01")}
    skipped = run_in(shop, lambda u: imp.apply(u, run.id, apply_changes=False, today=TODAY))
    assert (skipped.counts["skipped"], products(shop)["OIL-1"].sale_rate) == (1, Decimal("120.00"))

    again = upload(shop, csv_file("OIL-1,Coconut oil 500 ml,1513,BTL,125,18,2026-07-01,,taxable,"))
    run_in(shop, lambda u: imp.apply(u, again.id, apply_changes=True, today=TODAY))
    assert products(shop)["OIL-1"].sale_rate == Decimal("125.00")
    # History is kept: the old rate ends where the new one starts (L3-1).
    assert [(r, f) for r, f, _, _ in rates(shop, "OIL-1")] == [
        (Decimal("5.00"), date(2026, 4, 1)), (Decimal("18.00"), date(2026, 7, 1))]


def test_an_archived_product_comes_back_explicitly(shop):
    first = upload(shop, csv_file(OIL))
    run_in(shop, lambda u: imp.apply(u, first.id, apply_changes=True, today=TODAY))
    pg, biz, _ = shop
    pid = pg.client.get(f"/api/v1/b/{biz}/products?q=OIL", headers=as_user("alice")).json()["items"][0]["id"]
    pg.client.post(f"/api/v1/b/{biz}/products/{pid}/archive", headers=as_user("alice"))
    run = upload(shop, csv_file(OIL + " "))  # a different file, same content
    diff = preview(shop, run.id, "changed")[0]["diff"]
    assert diff == [{"field": "status", "saved": "archived", "file": "active"}]
    run_in(shop, lambda u: imp.apply(u, run.id, apply_changes=True, today=TODAY))
    assert products(shop)["OIL-1"].status == "active"


def test_rows_that_moved_after_the_preview_are_stale(shop):  # AC3-22, RM43-6
    first = upload(shop, csv_file(OIL))
    run_in(shop, lambda u: imp.apply(u, first.id, apply_changes=True, today=TODAY))
    run = upload(shop, csv_file(SOAP, "OIL-1,Coconut oil 500 ml,1513,BTL,130,5,2026-04-01,,taxable,", RICE))
    assert run.counts["new"] == 2 and run.counts["changed"] == 1
    pg, biz, _ = shop
    h = {**as_user("alice"), "Idempotency-Key": uuid.uuid4().hex}
    hand = {"code": "soap-1", "name": "Made by hand", "uqc": "PCS", "sale_rate": "1", "tax_category": "exempt"}
    assert pg.client.post(f"/api/v1/b/{biz}/products", json=hand, headers=h).status_code == 201
    pid = pg.client.get(f"/api/v1/b/{biz}/products?q=OIL", headers=as_user("alice")).json()["items"][0]["id"]
    r = pg.client.post(f"/api/v1/b/{biz}/products/{pid}/rates", json={"rate": "18", "valid_from": "2026-09-01"},
                       headers={**as_user("alice"), "Idempotency-Key": uuid.uuid4().hex})
    assert r.status_code == 201
    done = run_in(shop, lambda u: imp.apply(u, run.id, apply_changes=True, today=TODAY))
    assert (done.counts["applied"], done.counts["stale"]) == (1, 2)
    outcomes = {r["row_number"]: r["outcome"] for r in preview(shop, run.id)}
    assert outcomes == {2: "stale", 3: "stale", 4: "applied"}
    saved = products(shop)
    assert saved["soap-1"].name == "Made by hand" and saved["OIL-1"].sale_rate == Decimal("120.00")
    assert "RICE-1" in saved


def test_a_double_confirm_applies_once(shop):  # AC3-13
    run = upload(shop, csv_file(SOAP))
    run_in(shop, lambda u: imp.apply(u, run.id, apply_changes=True, today=TODAY))
    with pytest.raises(Conflict) as e:
        run_in(shop, lambda u: imp.apply(u, run.id, apply_changes=True, today=TODAY))
    assert e.value.code == "import_already_applied"
    assert len(products(shop)) == 1


def test_a_failed_apply_rolls_back_everything(shop):  # AC3-13: all or nothing
    run = upload(shop, csv_file(SOAP, OIL))

    def boom(u):
        imp.apply(u, run.id, apply_changes=True, today=TODAY)
        raise RuntimeError("worker died")

    with pytest.raises(RuntimeError):
        run_in(shop, boom)
    assert products(shop) == {}
    assert run_in(shop, lambda u: imp.get_run(u, run.id)).status == "preview"  # confirm can be retried


def test_limits_come_from_refdata(shop):
    with pytest.raises(Exception) as e:
        run_in(shop, lambda u: imp.start(u, "big.csv", 2 * 1024 * 1024 + 1, TODAY))
    assert e.value.code == "file_too_large"
    pg, biz, _ = shop
    with pg.owner.connect() as c:
        most = int(c.execute(text("select value from refdata.values where key = 'catalog.import.max_rows'")).scalar())
    many = csv_file(*[f"P-{i},Product {i},3401,PCS,1,18,01-04-2026,,taxable,no" for i in range(most + 1)])
    run = upload(shop, many)
    assert (run.status, run.error_code) == ("failed", "too_many_rows")


def test_an_xlsx_file_reads_like_a_csv(shop):
    openpyxl = pytest.importorskip("openpyxl")
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.append(HEADER.split(","))
    sheet.append(["SOAP-1", "Neem soap 100 g", "3401", "PCS", 45.5, 18, date(2026, 4, 1), None, "taxable", "no"])
    out = io.BytesIO()
    book.save(out)
    run = upload(shop, out.getvalue(), name="products.xlsx")
    assert run.status == "preview" and run.counts["new"] == 1, preview(shop, run.id)


def test_another_business_run_is_not_found(shop):
    pg, _, _ = shop
    run = upload(shop, csv_file(SOAP))
    other = new_business(pg, "bob")
    bob = user_id(pg.owner, "bob")
    with Session(pg.app_rw) as tx, tx.begin():
        ctx(tx, bob, other)
        uow = type("U", (), {})()
        uow.tx = tx
        uow.principal = Principal(user_sub="bob", request_id="t", user_id=bob, business_id=other, role="owner")
        with pytest.raises(Deny):
            imp.get_run(uow, run.id)
        with pytest.raises(Deny):
            imp.apply(uow, run.id, apply_changes=True, today=TODAY)
        assert tx.execute(text("select count(*) from catalog.import_rows")).scalar() == 0


def test_every_save_names_the_run_and_file_row_it_came_from(shop):  # CLAUDE.md rule 10
    pg, biz, _ = shop
    first = upload(shop, csv_file(OIL))
    run_in(shop, lambda u: imp.apply(u, first.id, apply_changes=True, today=TODAY))
    run = upload(shop, csv_file(RICE, "OIL-1,Coconut oil 1 l,1513,BTL,120,18,2026-07-01,,taxable,"))
    run_in(shop, lambda u: imp.apply(u, run.id, apply_changes=True, today=TODAY))
    with pg.owner.connect() as c:
        audited = {(r.action, r.data.get("import_run_id"), r.data.get("row_number")) for r in c.execute(text(
            "select action, data from platform.audit_log where business_id = :b and action like 'product.%'"),
            {"b": biz})}
        sources = c.execute(text(
            "select r.valid_from, i.run_id, i.row_number from catalog.product_rates r"
            " join catalog.import_rows i on i.id = r.source_import_row_id where r.business_id = :b"
            " order by r.valid_from"), {"b": biz}).all()
    first_id, run_id = str(first.id), str(run.id)
    assert {("product.created", first_id, 2), ("product.rate_added", first_id, 2), ("product.created", run_id, 2),
            ("product.updated", run_id, 3), ("product.rate_added", run_id, 3)} <= audited
    assert all(r[1] is not None for r in audited)  # nothing the import wrote looks like a hand edit
    assert [(f, str(r), n) for f, r, n in sources] == [
        (date(2026, 4, 1), first_id, 2), (date(2026, 7, 1), run_id, 3)]


def test_two_parses_of_the_same_file_at_once_leave_one_preview(shop):  # RM43-5, AC3-21
    """The second parse waits on import_runs_open_preview until the first commits, then
    supersedes it, as a later upload does: no 500, and a retry is safe."""
    pg, biz, alice = shop
    content = csv_file(SOAP)
    a = run_in(shop, lambda u: imp.start(u, "a.csv", len(content), TODAY))
    b = run_in(shop, lambda u: imp.start(u, "b.csv", len(content), TODAY))
    principal = Principal(user_sub="alice", request_id="test", user_id=alice, business_id=biz, role="owner")
    with Session(pg.app_rw) as first:
        first.begin()
        ctx(first, alice, biz)
        u = type("U", (), {"tx": first, "principal": principal})()
        assert imp.parse(u, a.id, content, TODAY).status == "preview"  # not committed yet
        with concurrent.futures.ThreadPoolExecutor(1) as pool:
            second = pool.submit(run_in, shop, lambda v: imp.parse(v, b.id, content, TODAY))
            time.sleep(0.5)
            assert not second.done()  # waiting on the open-preview index
            first.commit()
            assert second.result(timeout=10).status == "preview"
    old = run_in(shop, lambda u: imp.get_run(u, a.id))
    assert (old.status, old.superseded_by) == ("discarded", b.id)


def test_a_rate_that_no_longer_passes_at_confirm_is_left_stale(shop):  # #63 review nit
    """The preview checked the rate as refdata stood then; the apply checks it again. Here
    the date window has moved (the same check that a changed gst.rate_values would fail)."""
    run = upload(shop, csv_file(OIL, RICE))
    done = run_in(shop, lambda u: imp.apply(u, run.id, apply_changes=True, today=date(2025, 1, 1)))
    assert (done.counts["applied"], done.counts["stale"]) == (1, 1)
    assert set(products(shop)) == {"RICE-1"}  # RICE has no rate to re-check
    oil = preview(shop, run.id)[0]
    assert oil["outcome"] == "stale" and oil["errors"][0]["field"] == "gst_rate"
    assert "rate list changed" in oil["errors"][0]["message"]  # not mistaken for someone's edit
