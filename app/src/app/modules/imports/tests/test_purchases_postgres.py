"""Purchase invoices (R2-M2): upload, reading and the review, on PostgreSQL as app_rw. Skipped unless PG_ADMIN_URL is
set. Synthetic PDFs and made-up photos only. Reading is the text-layer reader in the real sandbox."""

import uuid

import pytest
from sqlalchemy import text

from .conftest import PG_ADMIN_URL, new_business, scalar
from .fixtures.pdf import invoice_page, pdf
from .test_uploads_postgres import get, post, run_jobs
from .test_uploads_postgres import shop as plain_shop  # noqa: F401  (a fixture)

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")


ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def check_character(first14):  # the GSTIN check character, worked out here so the test stands on its own
    total = sum((v := ALPHABET.index(ch) * (2 if i % 2 else 1)) // 36 + v % 36 for i, ch in enumerate(first14))
    return ALPHABET[(36 - total % 36) % 36]


@pytest.fixture()
def shop(plain_shop):  # noqa: F811
    """The business has chosen a type, as R2 needs; one test leaves it unset."""
    pg, biz, _ = plain_shop
    with pg.owner.begin() as c:
        c.execute(text("update business.profiles set business_type = 'retail' where business_id = :b"), {"b": biz})
    return plain_shop


def gstin(core="19ABCDE1234F1Z"):
    return core + check_character(core)


SUPPLIER = gstin()
assert len(SUPPLIER) == 15 and set(SUPPLIER) <= set(ALPHABET)
TWO_LINES = (("6109", "2", "PCS", "200.00", "18", "18.00", "18.00", ""),
             ("6110", "1", "NOS", "100.00", "18", "9.00", "9.00", ""))
JPEG = b"\xff\xd8\xff\xe0 made-up photo"


def send_file(shop_, name, content, ctype, sub="alice"):
    pg, biz, _ = shop_
    started = post(pg, f"/api/v1/b/{biz}/purchase-files", {"file_name": name, "size_bytes": len(content)}, sub=sub,
                   key=uuid.uuid4().hex)
    assert started.status_code == 201, started.text
    up = started.json()["upload"]
    assert pg.client.post(up["url"], data=up["fields"], files={"file": (name, content, ctype)}).status_code == 204
    done = post(pg, f"/api/v1/b/{biz}/purchase-files/{started.json()['file_id']}/complete", sub=sub)
    assert done.status_code == 202, done.text
    return started.json()["file_id"]


def read(shop_, name, content, ctype="application/pdf", sub="alice"):
    file_id = send_file(shop_, name, content, ctype, sub)
    run_jobs(shop_)
    pg, biz, _ = shop_
    f = get(pg, f"/api/v1/b/{biz}/purchase-files/{file_id}", sub).json()
    drafts = get(pg, f"/api/v1/b/{biz}/purchase-drafts?file_id={file_id}", sub).json()["drafts"]
    return f, drafts


def invoice(number="SUP-1", lines=TWO_LINES, **kw):
    return pdf([invoice_page(number, seller=SUPPLIER, lines=lines, **kw)])


def item(code="TEE-1", **kw):
    return {"code": code, "uqc": "PCS", "tax_category": "taxable", "gst_rate": "18", "rate_valid_from": "2026-04-01", **kw}


def line(draft_line=None, code="TEE-1", **kw):
    return {"draft_line_id": draft_line, "new_item": item(code), "product_name": "Cotton tee", "hsn": "6109", "quantity": "2", "unit": "PCS",
            "taxable_value": "200.00", "gst_rate": "18", "cgst": "18.00", "sgst": "18.00", **kw}


def confirm_body(draft, **kw):
    body = {"supplier_gstin": SUPPLIER, "supplier_name": "Demo Seller", "doc_number": "SUP-1", "doc_date": "2026-07-03",
            "invoice_total": "236.00"}
    body.update(kw)
    if "lines" not in kw:
        body["lines"] = [line(draft["lines"][0]["id"]),
                         line(draft["lines"][1]["id"], "TEE-2", hsn="6110", quantity="1", taxable_value="100.00",
                              cgst="9.00", sgst="9.00")]
    return body


def test_a_text_pdf_is_read_into_a_draft_the_business_reviews(shop):  # noqa: F811
    pg, biz, _ = shop
    f, drafts = read(shop, "bill.pdf", invoice())
    assert (f["status"], f["kind"], f["reject_reason"]) == ("read", "pdf", None)
    (d,) = drafts
    assert (d["reader"], d["supplier_gstin"], d["doc_number"], d["decision"]) == ("pdf_text_v1", SUPPLIER, "SUP-1", None)
    assert [(ln["hsn"], ln["quantity"], ln["taxable_value"]) for ln in d["lines"]] == [
        ("6109", "2", "200.00"), ("6110", "1", "100.00")]
    done = post(pg, f"/api/v1/b/{biz}/purchase-drafts/{d['id']}/confirm", confirm_body(d))
    assert done.status_code == 201, done.text
    assert (done.json()["doc_number"], done.json()["line_count"]) == ("SUP-1", 2)
    assert get(pg, f"/api/v1/b/{biz}/purchase-drafts/{d['id']}").json()["decision"] == "confirmed"
    listed = get(pg, f"/api/v1/b/{biz}/purchase-invoices").json()["invoices"]
    assert [(i["doc_number"], i["line_count"]) for i in listed] == [("SUP-1", 2)]
    back = scalar(pg.owner, "select count(*) from imports.purchase_review_lines where draft_line_id is not null")
    assert back == 2  # every confirmed line traces to the line that was read
    assert scalar(pg.owner, "select count(*) from catalog.products") == 2  # received at confirm, not before


def test_a_photo_is_kept_and_gets_a_blank_draft_the_business_types_in(shop):  # noqa: F811
    pg, biz, _ = shop
    f, (d,) = read(shop, "bill.jpg", JPEG, "image/jpeg")
    assert (f["status"], f["kind"]) == ("read", "image")
    assert (d["reader"], d["lines"], d["supplier_gstin"]) == ("none", [], None)
    assert set(d["unclear"]) == {"supplier_gstin", "doc_number", "doc_date", "invoice_total"}
    body = confirm_body(d, lines=[line()])
    assert post(pg, f"/api/v1/b/{biz}/purchase-drafts/{d['id']}/confirm", body).status_code == 201
    assert scalar(pg.owner, "select draft_line_id from imports.purchase_review_lines") is None  # typed in


def test_each_lines_description_is_offered_as_the_product_name_to_check(shop):  # noqa: F811  (#429, D-106)
    pg, biz, _ = shop
    _, (d,) = read(shop, "named.pdf", invoice(descriptions=("Cotton tee white", "Wool sweater"),
                                              wrapped={2: "navy, size M"}))
    assert [ln["description"] for ln in d["lines"]] == ["Cotton tee white", "Wool sweater navy, size M"]
    assert all("description" not in ln["unclear"] for ln in d["lines"])
    # Offered, not saved: the name the business confirms is the one it sends.
    done = post(pg, f"/api/v1/b/{biz}/purchase-drafts/{d['id']}/confirm", confirm_body(d))
    assert done.status_code == 201, done.text
    assert scalar(pg.owner, "select count(*) from catalog.products where name = 'Cotton tee'") == 2


def test_a_pdf_with_no_text_layer_becomes_a_blank_draft_not_a_refusal(shop):  # noqa: F811
    from .test_pdf_ocr_reader import image_pdf  # a picture-only page

    f, (d,) = read(shop, "scan.pdf", image_pdf(100, 100, b"\xff" * 10000))
    assert (f["status"], d["reader"], d["lines"]) == ("read", "none", [])


def test_the_same_file_twice_is_one_set_of_drafts(shop):  # noqa: F811
    pg, biz, _ = shop
    read(shop, "bill.pdf", invoice())
    f, drafts = read(shop, "bill-again.pdf", invoice())
    assert (f["status"], f["reject_reason"], drafts) == ("rejected", "already_uploaded", [])
    assert "already uploaded" in f["reject_message"]
    assert scalar(pg.owner, "select count(*) from imports.purchase_drafts") == 1


def test_a_complete_called_twice_is_one_job(shop):  # noqa: F811
    pg, biz, _ = shop
    file_id = send_file(shop, "bill.pdf", invoice(), "application/pdf")
    again = post(pg, f"/api/v1/b/{biz}/purchase-files/{file_id}/complete")
    assert again.status_code == 202
    assert len(run_jobs(shop)) == 1
    assert scalar(pg.owner, "select count(*) from imports.purchase_drafts") == 1


def test_a_wrong_kind_of_file_is_turned_away(shop):  # noqa: F811
    pg, biz, _ = shop
    f, drafts = read(shop, "bill.pdf", b"not a pdf at all")
    assert (f["status"], f["reject_reason"], drafts) == ("rejected", "not_a_pdf", [])
    f, _ = read(shop, "bill.jpg", b"not a picture", "image/jpeg")
    assert f["reject_reason"] == "not_an_image"
    r = post(pg, f"/api/v1/b/{biz}/purchase-files", {"file_name": "bill.docx", "size_bytes": 10}, key="k-docx")
    assert (r.status_code, r.json()["error"]["code"]) == (422, "file_type_not_allowed")


def test_confirm_checks_the_values_on_the_server(shop):  # noqa: F811
    pg, biz, _ = shop
    _, (d,) = read(shop, "bill.pdf", invoice())
    url = f"/api/v1/b/{biz}/purchase-drafts/{d['id']}/confirm"
    good = confirm_body(d)

    def refused(code, **kw):
        r = post(pg, url, {**good, **kw})
        assert (r.status_code, r.json()["error"]["code"]) == (422, code), r.text

    refused("supplier_gstin_invalid", supplier_gstin="19ABCDE1234F1Z0")  # bad check character
    refused("doc_number_invalid", doc_number="  ")
    refused("doc_date_in_future", doc_date="2027-01-01")
    refused("lines_invalid", lines=[])
    refused("product_name_invalid", lines=[line(product_name=" ")])
    refused("hsn_invalid", lines=[line(hsn="61")])
    refused("tax_split_invalid", lines=[line(igst="36.00")])
    refused("draft_line_invalid", lines=[line(str(uuid.uuid4()))])
    refused("draft_line_invalid", lines=[line(d["lines"][0]["id"]), line(d["lines"][0]["id"])])
    assert post(pg, url, {**good, "lines": [line(quantity="0")]}).status_code == 422
    assert post(pg, url, {**good, "lines": [line(taxable_value="-1")]}).status_code == 422
    assert scalar(pg.owner, "select count(*) from imports.purchase_reviews") == 0


def test_a_draft_is_decided_once_and_an_invoice_is_confirmed_once(shop):  # noqa: F811
    pg, biz, _ = shop
    _, (d,) = read(shop, "bill.pdf", invoice())
    url = f"/api/v1/b/{biz}/purchase-drafts/{d['id']}"
    assert post(pg, url + "/confirm", confirm_body(d)).status_code == 201
    again = post(pg, url + "/confirm", confirm_body(d))
    assert (again.status_code, again.json()["error"]["code"]) == (409, "purchase_already_reviewed")
    assert post(pg, url + "/discard").status_code == 409
    # the same supplier invoice number from another file is a duplicate, case and spaces folded
    _, (d2,) = read(shop, "other.pdf", invoice("SUP-2"))
    dup = post(pg, f"/api/v1/b/{biz}/purchase-drafts/{d2['id']}/confirm", confirm_body(d2, doc_number=" sup-1 "))
    assert (dup.status_code, dup.json()["error"]["code"]) == (409, "purchase_already_confirmed")
    assert scalar(pg.owner, "select count(*) from imports.purchase_reviews") == 1


def test_discarding_keeps_the_draft_and_blocks_nothing_else(shop):  # noqa: F811
    pg, biz, _ = shop
    _, (d,) = read(shop, "bill.pdf", invoice())
    out = post(pg, f"/api/v1/b/{biz}/purchase-drafts/{d['id']}/discard")
    assert (out.status_code, out.json()["decision"]) == (200, "discarded")
    assert get(pg, f"/api/v1/b/{biz}/purchase-drafts?open_only=true").json()["drafts"] == []
    assert len(get(pg, f"/api/v1/b/{biz}/purchase-drafts").json()["drafts"]) == 1
    assert get(pg, f"/api/v1/b/{biz}/purchase-invoices").json()["invoices"] == []


def test_reviews_and_drafts_are_insert_only(shop):  # noqa: F811
    pg, biz, _ = shop
    _, (d,) = read(shop, "bill.pdf", invoice())
    post(pg, f"/api/v1/b/{biz}/purchase-drafts/{d['id']}/confirm", confirm_body(d))
    for table in ("purchase_drafts", "purchase_draft_lines", "purchase_reviews", "purchase_review_lines"):
        with pytest.raises(Exception, match="insert-only|permission denied"):
            with pg.owner.connect() as c:
                c.execute(text(f"update imports.{table} set business_id = business_id"))
        with pytest.raises(Exception, match="insert-only|permission denied"):
            with pg.owner.connect() as c:
                c.execute(text(f"delete from imports.{table}"))


def test_another_business_cannot_see_or_decide_them(shop):  # noqa: F811
    pg, biz, _ = shop
    file_id = send_file(shop, "bill.pdf", invoice(), "application/pdf")
    run_jobs(shop)
    d = get(pg, f"/api/v1/b/{biz}/purchase-drafts?file_id={file_id}").json()["drafts"][0]
    other = new_business(pg, "bob")
    with pg.owner.begin() as c:
        c.execute(text("update business.profiles set business_type = 'retail' where business_id = :b"), {"b": other})
    assert get(pg, f"/api/v1/b/{other}/purchase-files/{file_id}", sub="bob").status_code == 404
    assert get(pg, f"/api/v1/b/{other}/purchase-drafts/{d['id']}", sub="bob").status_code == 404
    assert post(pg, f"/api/v1/b/{other}/purchase-drafts/{d['id']}/confirm", confirm_body(d), sub="bob").status_code == 404
    assert post(pg, f"/api/v1/b/{other}/purchase-drafts/{d['id']}/discard", sub="bob").status_code == 404
    assert post(pg, f"/api/v1/b/{other}/purchase-files/{file_id}/complete", sub="bob").status_code == 404
    assert get(pg, f"/api/v1/b/{other}/purchase-drafts", sub="bob").json()["drafts"] == []
    assert get(pg, f"/api/v1/b/{biz}/purchase-drafts/{d['id']}", sub="bob").status_code == 404  # not a member of biz


def test_roles(shop):  # noqa: F811
    pg, biz, _ = shop
    _, (d,) = read(shop, "bill.pdf", invoice())
    base = f"/api/v1/b/{biz}"
    assert get(pg, f"{base}/purchase-drafts", sub="cathy").status_code == 200  # the CA reads
    assert post(pg, f"{base}/purchase-drafts/{d['id']}/confirm", confirm_body(d), sub="cathy").status_code == 404
    assert post(pg, f"{base}/purchase-drafts/{d['id']}/discard", sub="cathy").status_code == 404
    assert post(pg, f"{base}/purchase-files", {"file_name": "a.pdf", "size_bytes": 5}, sub="cathy",
                key="k-cathy").status_code == 404
    assert post(pg, f"{base}/purchase-drafts/{d['id']}/discard", sub="adam").status_code == 200  # an admin decides


def test_no_value_reaches_the_audit_log(shop):  # noqa: F811
    pg, biz, _ = shop
    _, (d,) = read(shop, "bill.pdf", invoice())
    post(pg, f"/api/v1/b/{biz}/purchase-drafts/{d['id']}/confirm", confirm_body(d))
    rows = scalar(pg.owner, "select string_agg(action || coalesce(data::text, ''), ' ') from platform.audit_log"
                            " where action like 'imports.purchase%'")
    assert "imports.purchase_confirmed" in rows
    for secret in (SUPPLIER, "SUP-1", "Cotton tee", "Demo Seller", "200.00"):
        assert secret not in rows


def test_a_business_that_has_not_chosen_a_type_is_not_held_up(plain_shop):  # noqa: F811  (D-095)
    pg, biz, _ = plain_shop
    base = f"/api/v1/b/{biz}"
    assert post(pg, f"{base}/purchase-files", {"file_name": "a.pdf", "size_bytes": 5}, key="k-type").status_code == 201
    d = uuid.uuid4()
    for path in ("confirm", "discard"):  # no such draft: not found, never "choose a business type"
        assert post(pg, f"{base}/purchase-drafts/{d}/{path}", {}).json()["error"]["code"] != "business_type_required"
    assert get(pg, f"{base}/purchase-drafts").status_code == 200


def test_confirming_creates_the_catalog_items_and_receives_the_stock_once(shop):  # noqa: F811
    pg, biz, _ = shop
    _, (d,) = read(shop, "bill.pdf", invoice())
    done = post(pg, f"/api/v1/b/{biz}/purchase-drafts/{d['id']}/confirm", confirm_body(d))
    assert done.status_code == 201, done.text
    got = done.json()["received"]
    assert [(r["line_no"], r["created_product"], r["price_needed"]) for r in got] == [(1, True, True), (2, True, True)]
    moves = pg.owner.connect().execute(text(
        "select p.code, m.quantity, m.kind, m.unit_cost from catalog.stock_movements m"
        " join catalog.products p on p.id = m.product_id order by p.code")).all()
    assert [(c, str(q), k, str(u)) for c, q, k, u in moves] == [
        ("TEE-1", "2.000", "purchase_in", "100.00"), ("TEE-2", "1.000", "purchase_in", "100.00")]
    ids = scalar(pg.owner, "select count(*) from imports.purchase_review_lines l join catalog.products p"
                           " on p.id = l.product_id and l.created_product")
    assert ids == 2


def test_a_line_can_go_into_an_existing_product_and_a_taken_code_undoes_the_whole_confirm(shop):  # noqa: F811
    pg, biz, _ = shop
    _, (d,) = read(shop, "bill.pdf", invoice())
    base = f"/api/v1/b/{biz}"
    first = post(pg, f"{base}/purchase-drafts/{d['id']}/confirm", confirm_body(d))
    assert first.status_code == 201
    pid = first.json()["received"][0]["product_id"]
    assert get(pg, f"{base}/purchase-code-check?code=tee-1").json() == {"code": "tee-1", "available": False}
    assert get(pg, f"{base}/purchase-code-check?code=NEW-9").json()["available"] is True
    _, (d2,) = read(shop, "second.pdf", invoice("SUP-2", lines=TWO_LINES[:1]))
    # one line into the existing product, one new line whose code is taken: nothing is saved
    bad = confirm_body(d2, doc_number="SUP-2", lines=[
        {**line(d2["lines"][0]["id"]), "new_item": None, "product_id": pid}, line(None, "TEE-2")])
    r = post(pg, f"{base}/purchase-drafts/{d2['id']}/confirm", bad)
    assert (r.status_code, r.json()["error"]["code"]) == (422, "code_taken")
    assert scalar(pg.owner, "select count(*) from imports.purchase_reviews where decision = 'confirmed'") == 1
    assert scalar(pg.owner, "select count(*) from catalog.stock_movements") == 2
    ok = confirm_body(d2, doc_number="SUP-2", lines=[{**line(d2["lines"][0]["id"]), "new_item": None, "product_id": pid}])
    out = post(pg, f"{base}/purchase-drafts/{d2['id']}/confirm", ok)
    assert out.status_code == 201 and out.json()["received"][0]["created_product"] is False
    assert scalar(pg.owner, "select sum(quantity) from catalog.stock_movements where product_id = :p", p=pid) == 4


def test_a_line_names_an_existing_product_or_a_new_one_never_both_or_neither(shop):  # noqa: F811
    pg, biz, _ = shop
    _, (d,) = read(shop, "bill.pdf", invoice())
    url = f"/api/v1/b/{biz}/purchase-drafts/{d['id']}/confirm"
    both = post(pg, url, confirm_body(d, lines=[{**line(), "product_id": str(uuid.uuid4())}]))
    neither = post(pg, url, confirm_body(d, lines=[{**line(), "new_item": None}]))
    assert {both.json()["error"]["code"], neither.json()["error"]["code"]} == {"product_or_new_item"}
    unknown = post(pg, url, confirm_body(d, lines=[{**line(), "new_item": None, "product_id": str(uuid.uuid4())}]))
    assert unknown.status_code == 404
    assert scalar(pg.owner, "select count(*) from catalog.stock_movements") == 0


# ---- Staff review of M2 (r2-review-1): B1, B2, S1, S2, S3 ----

def test_an_amount_with_look_alike_digits_is_refused_not_a_server_error(shop):  # noqa: F811
    pg, biz, _ = shop
    _, (d,) = read(shop, "bill.pdf", invoice())
    url = f"/api/v1/b/{biz}/purchase-drafts/{d['id']}/confirm"
    for bad in ("²", "٣", "1.²", "１２", "1e3", "-1", " ", "1.2.3"):
        r = post(pg, url, confirm_body(d, lines=[line(d["lines"][0]["id"], quantity=bad)]))
        assert (r.status_code, r.json()["error"]["code"]) == (422, "amount_invalid"), bad
    assert scalar(pg.owner, "select count(*) from imports.purchase_reviews") == 0


def test_two_files_of_one_invoice_confirmed_together_are_a_conflict_not_a_server_error(shop, monkeypatch):  # noqa: F811
    from app.modules.imports import purchases

    pg, biz, _ = shop
    _, (d1,) = read(shop, "a.pdf", invoice())
    _, (d2,) = read(shop, "b.pdf", invoice(lines=TWO_LINES[:1]))  # the same supplier invoice number, another file
    assert post(pg, f"/api/v1/b/{biz}/purchase-drafts/{d1['id']}/confirm", confirm_body(d1)).status_code == 201
    # the race: the other request's check saw nothing, so only the unique index stops the second insert
    monkeypatch.setattr(purchases, "_already_confirmed", lambda *a, **k: False)
    body = confirm_body(d2, lines=[line(d2["lines"][0]["id"], "NEW-1")])
    r = post(pg, f"/api/v1/b/{biz}/purchase-drafts/{d2['id']}/confirm", body)
    assert (r.status_code, r.json()["error"]["code"]) == (409, "purchase_already_confirmed")
    assert scalar(pg.owner, "select count(*) from imports.purchase_reviews where decision = 'confirmed'") == 1
    assert scalar(pg.owner, "select count(*) from catalog.stock_movements") == 2


def test_a_retried_confirm_with_the_same_key_returns_the_first_answer(shop):  # noqa: F811
    pg, biz, _ = shop
    _, (d,) = read(shop, "bill.pdf", invoice())
    url = f"/api/v1/b/{biz}/purchase-drafts/{d['id']}"
    first = post(pg, url + "/confirm", confirm_body(d), key="k-confirm-1")
    again = post(pg, url + "/confirm", confirm_body(d), key="k-confirm-1")
    assert first.status_code == again.status_code == 201
    assert again.json() == first.json() and len(again.json()["received"]) == 2
    other = post(pg, url + "/confirm", confirm_body(d, doc_number="X"), key="k-confirm-1")
    assert other.json()["error"]["code"] == "idempotency_mismatch"
    assert scalar(pg.owner, "select count(*) from catalog.stock_movements") == 2
    # discard replays the same way
    _, (d2,) = read(shop, "other.pdf", invoice("SUP-9"))
    u2 = f"/api/v1/b/{biz}/purchase-drafts/{d2['id']}/discard"
    a, b = post(pg, u2, key="k-discard-1"), post(pg, u2, key="k-discard-1")
    assert a.status_code == b.status_code == 200 and a.json() == b.json()


def test_a_rate_over_100_is_refused_and_a_tax_mismatch_is_a_warning_only(shop):  # noqa: F811
    pg, biz, _ = shop
    _, (d,) = read(shop, "bill.pdf", invoice())
    url = f"/api/v1/b/{biz}/purchase-drafts/{d['id']}/confirm"
    r = post(pg, url, confirm_body(d, lines=[line(d["lines"][0]["id"], gst_rate="100.01")]))
    assert (r.status_code, r.json()["error"]["code"]) == (422, "gst_rate_invalid")
    wrong = [line(d["lines"][0]["id"], cgst="10.00", sgst="10.00"),  # 200 x 18% is 36, not 20
             line(d["lines"][1]["id"], "TEE-2", hsn="6110", quantity="1", taxable_value="100.00", cgst="9.00", sgst="9.01")]
    ok = post(pg, url, confirm_body(d, lines=wrong))
    assert ok.status_code == 201
    assert ok.json()["warnings"] == [{"line_no": 1, "code": "tax_differs_from_rate"}]  # a paisa apart is not a warning
    # what was typed is stored as typed, never recomputed
    assert scalar(pg.owner, "select cgst from imports.purchase_review_lines where line_no = 1") == 10


def test_a_unit_that_differs_from_the_existing_products_is_a_warning(shop):  # noqa: F811
    pg, biz, _ = shop
    _, (d,) = read(shop, "bill.pdf", invoice())
    base = f"/api/v1/b/{biz}"
    first = post(pg, f"{base}/purchase-drafts/{d['id']}/confirm", confirm_body(d))
    pid = first.json()["received"][0]["product_id"]
    for n, (unit, expect) in enumerate((("PCS", []), ("pcs", []), ("BOX", [{"line_no": 1, "code": "unit_differs_from_product"}]))):
        _, (dx,) = read(shop, f"x-{n}.pdf", invoice(f"UNIT-{n}", lines=TWO_LINES[:1]))
        body = confirm_body(dx, doc_number=f"UNIT-{n}", lines=[
            {**line(dx["lines"][0]["id"], unit=unit), "new_item": None, "product_id": pid}])
        r = post(pg, f"{base}/purchase-drafts/{dx['id']}/confirm", body)
        assert r.status_code == 201 and r.json()["warnings"] == expect, unit
