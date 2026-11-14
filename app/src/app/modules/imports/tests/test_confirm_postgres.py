"""Confirm: a staged own-invoice run becomes documents and lines, each new document is assigned to its return once
(R1-M7 slice 2), and the user's "I have none this month". On PostgreSQL through the real reader. Skipped unless
PG_ADMIN_URL is set."""

import uuid

import pytest
from sqlalchemy import text

from app.modules.imports import readers
from app.modules.imports.readers import register_readers
from app.modules.filing.interface import PeriodLocked

from .conftest import PG_ADMIN_URL, new_business, scalar
from .fixtures import own_excel as fx
from .test_parse_postgres import GSTIN, state
from .test_uploads_postgres import get, post, run_jobs, shop, upload  # noqa: F401  (the shop fixture)

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
FULL = "61091000"
OCT = "05-10-2026"


@pytest.fixture(autouse=True)
def real_readers(monkeypatch):
    monkeypatch.setenv("DEMO_READERS", "1")  # opens the verified-layout gate for these synthetic files
    readers.clear_for_tests()
    register_readers()
    yield
    readers.clear_for_tests()


def monthly(shop):  # noqa: F811
    pg, biz, _ = shop
    r = post(pg, f"/api/v1/b/{biz}/filing-profile/frequency", {"frequency": "monthly", "effective_from": "2026-10-01"},
             key=uuid.uuid4().hex)
    assert r.status_code in (200, 201), r.text


def line(number, **kw):
    return fx.line(number, **{"gstin": GSTIN, "hsn": FULL, "date": OCT, **kw})


def stage(shop, rows, name="a.xlsx"):  # noqa: F811
    upload_id, _ = upload(shop, "own_invoices_excel", name, fx.workbook(rows), XLSX)
    run_jobs(shop)
    return state(shop, upload_id)["run_id"]


def confirm(shop, run_id, changed=(), sub="alice", key=None):  # noqa: F811
    pg, biz, _ = shop
    return post(pg, f"/api/v1/b/{biz}/runs/{run_id}/confirm", {"changed": list(changed)}, sub=sub,
                key=key or uuid.uuid4().hex)


def q(pg, sql):
    return pg.owner.connect().execute(text(sql)).all()


def month(shop):  # noqa: F811
    return [line("INV-1"), line("INV-1", hsn="611010", taxable="100", cgst="9", sgst="9", total="236"),
            fx.inter("INV-2", gstin=GSTIN, hsn=FULL, date=OCT), line("INV-3", buyer="29DEMOC9999C1Z1"),
            line("CN-1", kind="Credit note", original="INV-1", original_date=OCT, taxable="50", cgst="4.5", sgst="4.5",
                 total="59"),
            line("DN-1", kind="Debit note", original="INV-1", original_date=OCT)]


def test_a_run_is_confirmed_into_documents_assigned_once_to_its_return(shop):  # noqa: F811
    pg, biz, _ = shop
    monthly(shop)
    run_id = stage(shop, month(shop))
    out = confirm(shop, run_id)
    assert out.status_code == 200, (out.text, get(pg, f"/api/v1/b/{biz}/runs/{run_id}/confirm-check").json()["blockers"])
    assert out.json() == {"run_id": run_id, "documents": 5, "lines": 6, "accepted_changes": 0, "skipped_changes": 0}
    docs = {r.doc_number: r for r in q(pg, "select * from imports.documents")}
    assert {k: v.supply_class for k, v in docs.items()} == {
        "INV-1": "B2CS", "INV-2": "B2CS", "INV-3": "B2B", "CN-1": "B2CS", "DN-1": None}
    assert docs["INV-2"].is_inter_state and not docs["INV-1"].is_inter_state
    assert docs["INV-1"].return_instance_id is not None and docs["INV-1"].return_period == "2026-10"
    assert docs["DN-1"].return_instance_id is None  # no section for a debit note yet
    assert not docs["CN-1"].original_not_in_app
    assert scalar(pg.owner, "select count(*) from imports.document_lines where document_id = "
                  f"'{docs['INV-1'].id}'") == 2
    assert scalar(pg.owner, "select status from imports.import_runs") == "confirmed"
    audit = q(pg, "select data::text from platform.audit_log where action = 'imports.confirmed'")
    assert len(audit) == 1 and GSTIN not in audit[0][0] and "INV-1" not in audit[0][0]
    again = confirm(shop, run_id)
    assert again.status_code == 409 and again.json()["error"]["code"] == "run_not_staged"


def test_a_credit_note_whose_original_is_not_in_the_app_is_flagged_and_netted_not_guessed(shop):  # noqa: F811
    pg, _, _ = shop
    monthly(shop)
    run_id = stage(shop, [line("CN-9", kind="Credit note", original="INV-77", original_date="01-09-2026")])
    assert confirm(shop, run_id).status_code == 200
    row = q(pg, "select supply_class, original_not_in_app from imports.documents")[0]
    assert (row.supply_class, row.original_not_in_app) == ("B2CS", True)


def test_a_blocked_run_writes_nothing(shop, monkeypatch):  # noqa: F811
    pg, _, _ = shop
    monthly(shop)
    monkeypatch.delenv("DEMO_READERS")
    run_id = stage(shop, [line("INV-1")])
    out = confirm(shop, run_id)
    assert out.status_code == 409 and out.json()["error"]["code"] == "confirm_blocked"
    assert scalar(pg.owner, "select count(*) from imports.documents") == 0
    assert scalar(pg.owner, "select status from imports.import_runs") == "staged"


def test_a_filing_frequency_not_set_refuses_and_leaves_nothing_behind(shop):  # noqa: F811
    pg, _, _ = shop
    run_id = stage(shop, [line("INV-1")])
    out = confirm(shop, run_id)
    assert out.status_code == 409 and out.json()["error"]["code"] == "filing_frequency_not_set"
    assert scalar(pg.owner, "select count(*) from imports.documents") == 0
    assert scalar(pg.owner, "select status from imports.import_runs") == "staged"


def test_a_locked_return_refuses_the_whole_confirm(shop, monkeypatch):  # noqa: F811
    pg, _, _ = shop
    monthly(shop)

    def locked(*a, **k):
        raise PeriodLocked("period_locked", "Your Oct 2026 return is already filed.")

    monkeypatch.setattr("app.modules.imports.confirm.target_return_instance", locked)
    run_id = stage(shop, [line("INV-1"), line("INV-2")])
    out = confirm(shop, run_id)
    assert out.status_code == 409 and out.json()["error"]["code"] == "period_locked"
    assert scalar(pg.owner, "select count(*) from imports.documents") == 0
    assert scalar(pg.owner, "select count(*) from imports.row_resolutions") == 0


def test_set_aside_rows_are_left_out_and_undecided_rows_block(shop):  # noqa: F811
    pg, biz, _ = shop
    monthly(shop)
    run_id = stage(shop, [line("INV-1"), line("INV-2", hsn="")])
    assert confirm(shop, run_id).json()["error"]["code"] == "confirm_blocked"
    held = get(pg, f"/api/v1/b/{biz}/runs/{run_id}/rows?status=held").json()["rows"][0]
    post(pg, f"/api/v1/b/{biz}/rows/{held['row_id']}/resolve", {"action": "set_aside", "note": "Not mine"}, key="s1")
    assert confirm(shop, run_id).json()["documents"] == 1
    assert [r.doc_number for r in q(pg, "select doc_number from imports.documents")] == ["INV-1"]


def test_a_fixed_hsn_is_what_the_line_keeps_and_the_row_stays_as_the_file_said(shop):  # noqa: F811
    pg, biz, _ = shop
    monthly(shop)
    run_id = stage(shop, [line("INV-1", hsn="")])
    held = get(pg, f"/api/v1/b/{biz}/runs/{run_id}/rows?status=held").json()["rows"][0]
    post(pg, f"/api/v1/b/{biz}/rows/{held['row_id']}/resolve",
         {"action": "enter_hsn", "note": "Checked the invoice", "value": FULL}, key="f1")
    assert confirm(shop, run_id).status_code == 200
    got = q(pg, "select hsn, hsn_from from imports.document_lines")[0]
    assert (got.hsn, got.hsn_from) == (FULL, "fixed")


def corrected(shop, first_rows, second_rows):  # noqa: F811
    monthly(shop)
    one = stage(shop, first_rows, "one.xlsx")
    assert confirm(shop, one).status_code == 200
    two = stage(shop, second_rows, "two.xlsx")
    return two


def changed_rows(shop, run_id):  # noqa: F811
    pg, biz, _ = shop
    return [r for r in get(pg, f"/api/v1/b/{biz}/runs/{run_id}/rows").json()["rows"] if r["status"] == "changed"]


def test_a_changed_line_needs_a_choice_and_an_accepted_one_supersedes_the_old_line(shop):  # noqa: F811
    pg, _, _ = shop
    two = corrected(shop, [line("INV-1")], [line("INV-1", taxable="210", cgst="18.9", sgst="18.9", total="247.8")])
    rows = changed_rows(shop, two)
    assert len(rows) == 1
    undecided = confirm(shop, two)
    assert undecided.status_code == 422 and undecided.json()["error"]["code"] == "changes_undecided"
    assert scalar(pg.owner, "select count(*) from imports.document_lines") == 1
    out = confirm(shop, two, [{"row_id": rows[0]["row_id"], "choice": "accept"}])
    assert out.status_code == 200 and out.json()["accepted_changes"] == 1 and out.json()["documents"] == 0
    lines = q(pg, "select id, supersedes, taxable_value from imports.document_lines order by created_at")
    assert len(lines) == 2 and lines[1].supersedes == lines[0].id and str(lines[1].taxable_value) == "210"


def test_a_skipped_change_keeps_the_earlier_line_and_a_change_to_the_date_needs_a_correction_note(shop):  # noqa: F811
    pg, _, _ = shop
    two = corrected(shop, [line("INV-1")], [line("INV-1", taxable="210", cgst="18.9", sgst="18.9", total="247.8")])
    row = changed_rows(shop, two)[0]
    out = confirm(shop, two, [{"row_id": row["row_id"], "choice": "skip"}])
    assert out.status_code == 200 and out.json()["skipped_changes"] == 1
    assert scalar(pg.owner, "select count(*) from imports.document_lines") == 1


def test_accepting_a_changed_date_of_a_confirmed_document_is_refused(shop):  # noqa: F811
    pg, _, _ = shop
    two = corrected(shop, [line("INV-1")], [line("INV-1", date="06-10-2026")])
    row = changed_rows(shop, two)[0]
    out = confirm(shop, two, [{"row_id": row["row_id"], "choice": "accept"}])
    assert out.status_code == 409 and out.json()["error"]["code"] == "change_needs_correction_note"
    assert scalar(pg.owner, "select count(*) from imports.document_lines") == 1
    assert scalar(pg.owner, "select count(*) from imports.row_resolutions") == 0  # the refusal rolled back too


def test_a_later_file_adding_a_line_to_a_confirmed_document_attaches_it(shop):  # noqa: F811
    pg, _, _ = shop
    monthly(shop)
    assert confirm(shop, stage(shop, [line("INV-1")], "one.xlsx")).status_code == 200
    two = stage(shop, [line("INV-1"), line("INV-1", hsn="611010", taxable="100", cgst="9", sgst="9", total="236")], "two.xlsx")
    out = confirm(shop, two)
    assert out.status_code == 200 and (out.json()["documents"], out.json()["lines"]) == (0, 1)
    assert [r.line_pos for r in q(pg, "select line_pos from imports.document_lines order by line_pos")] == [1, 2]


def test_documents_and_lines_are_insert_only_even_for_the_owner(shop):  # noqa: F811
    pg, _, _ = shop
    monthly(shop)
    confirm(shop, stage(shop, [line("INV-1")]))
    for sql in ("update imports.documents set doc_total = 1", "delete from imports.document_lines",
                "truncate imports.documents cascade"):
        with pytest.raises(Exception, match="insert-only"):
            with pg.owner.begin() as c:
                c.execute(text(sql))


def test_confirm_is_for_owner_and_admin_only_and_other_businesses_get_404(shop):  # noqa: F811
    pg, biz, _ = shop
    monthly(shop)
    run_id = stage(shop, [line("INV-1")])
    assert confirm(shop, run_id, sub="bill").status_code == 404
    assert confirm(shop, run_id, sub="cathy").status_code == 404  # the CA reads uploads, does not confirm
    other = new_business(pg, "mallory")
    assert post(pg, f"/api/v1/b/{other}/runs/{run_id}/confirm", {"changed": []}, sub="mallory", key="m1").status_code == 404
    assert confirm(shop, run_id, sub="adam").status_code == 200


def test_the_same_confirm_request_twice_answers_alike(shop):  # noqa: F811
    monthly(shop)
    run_id = stage(shop, [line("INV-1")])
    one = confirm(shop, run_id, key="same")
    two = confirm(shop, run_id, key="same")
    assert one.status_code == two.status_code == 200 and one.json() == two.json()


def test_flipkart_style_reports_without_a_confirmed_treatment_are_refused(shop):  # noqa: F811
    pg, biz, _ = shop
    from .fixtures import amazon as fxa
    from .fixtures import meesho as fxm

    z = fxa.zipped({"tcs_sales.xlsx": fxm.workbook([fxm.sale("1", gstin=GSTIN)])})
    upload_id, _ = upload(shop, "meesho", "m.zip", z, "application/zip")
    run_jobs(shop)
    run_id = state(shop, upload_id)["run_id"]
    codes = [b["code"] for b in get(pg, f"/api/v1/b/{biz}/runs/{run_id}/confirm-check").json()["blockers"]]
    assert "treatment_unconfirmed" in codes and "period_date_unconfirmed" in codes
    blocker = next(b for b in get(pg, f"/api/v1/b/{biz}/runs/{run_id}/confirm-check").json()["blockers"]
                   if b["code"] == "treatment_unconfirmed")
    assert "M-4" in blocker["ca_items"] and "nothing is wrong" in blocker["label"].lower()
    assert confirm(shop, run_id).json()["error"]["code"] == "confirm_blocked"


def test_none_this_month_is_kept_once_listed_and_refuses_the_future_and_unknown_sections(shop):  # noqa: F811
    pg, biz, _ = shop
    path = f"/api/v1/b/{biz}/uploads/none-this-month"
    assert post(pg, path, {"section": "own_invoices_excel", "month": "2026-10"}, key="n1").json() == {
        "section": "own_invoices_excel", "month": "2026-10"}
    post(pg, path, {"section": "own_invoices_excel", "month": "2026-10"}, key="n2")
    post(pg, path, {"section": "amazon", "month": "2026-09"}, key="n3")
    assert get(pg, path).json()["items"] == [{"section": "amazon", "month": "2026-09"},
                                             {"section": "own_invoices_excel", "month": "2026-10"}]
    assert scalar(pg.owner, "select count(*) from imports.period_confirmations") == 2
    assert scalar(pg.owner, "select count(*) from platform.audit_log where action = 'imports.none_this_month'") == 2
    assert post(pg, path, {"section": "own_invoices_excel", "month": "2026-12"}, key="n4").json()["error"]["code"] == "month_in_future"
    assert post(pg, path, {"section": "own_invoices_pdf", "month": "2026-10"}, key="n5").json()["error"]["code"] == "unknown_section"
    assert post(pg, path, {"section": "amazon", "month": "2026-13"}, key="n6").json()["error"]["code"] == "invalid_month"
    assert post(pg, path, {"section": "amazon", "month": "2026-10"}, sub="bill", key="n7").status_code == 404
    assert get(pg, path, sub="cathy").status_code == 200 and get(pg, path, sub="bill").status_code == 404
    other = new_business(pg, "mallory")
    assert get(pg, f"/api/v1/b/{other}/uploads/none-this-month", sub="mallory").json()["items"] == []


def test_a_row_with_no_readable_date_never_reaches_a_confirm(shop):  # noqa: F811
    """Staging makes a blank or unreadable document date an invalid row, which blocks the confirm; no row
    can be assigned to a return without a date."""
    monthly(shop)
    run_id = stage(shop, [line("INV-1"), line("INV-2", date="")])
    out = confirm(shop, run_id)
    assert out.status_code == 409 and out.json()["error"]["code"] == "confirm_blocked"
    pg = shop[0]
    assert q(pg, "select count(*) from imports.documents")[0][0] == 0
    codes = [b["code"] for b in get(pg, f"/api/v1/b/{shop[1]}/runs/{run_id}/confirm-check").json()["blockers"]]
    assert "rows_invalid" in codes
