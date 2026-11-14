"""The confirm check through the API on PostgreSQL (R1-M7 slice 1): own invoices through the real reader, Meesho for
the cross-run clash. Skipped unless PG_ADMIN_URL is set."""

import json

import pytest

from app.modules.imports import readers
from app.modules.imports.readers import register_readers

from .conftest import PG_ADMIN_URL, new_business
from .fixtures import amazon as fxa
from .fixtures import meesho as fxm
from .fixtures import own_excel as fx
from .test_parse_postgres import GSTIN, state
from .test_uploads_postgres import get, post, run_jobs, shop, upload  # noqa: F401  (the shop fixture)

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
FULL = "61091000"


@pytest.fixture(autouse=True)
def real_readers():
    readers.clear_for_tests()
    register_readers()
    yield
    readers.clear_for_tests()


@pytest.fixture()
def demo(monkeypatch):
    monkeypatch.setenv("DEMO_READERS", "1")


def stage(shop, rows, name="a.xlsx", section="own_invoices_excel"):  # noqa: F811
    upload_id, _ = upload(shop, section, name, fx.workbook(rows), XLSX)
    run_jobs(shop)
    return state(shop, upload_id)["run_id"]


def check(shop, run_id, sub="alice"):  # noqa: F811
    pg, biz, _ = shop
    return get(pg, f"/api/v1/b/{biz}/runs/{run_id}/confirm-check", sub=sub)


def codes(out):
    return [b["code"] for b in out.json()["blockers"]]


def rows(shop, run_id):  # noqa: F811
    pg, biz, _ = shop
    return get(pg, f"/api/v1/b/{biz}/runs/{run_id}/rows").json()["rows"]


def good(number="INV-1", **kw):
    return fx.line(number, **{"gstin": GSTIN, "hsn": FULL, **kw})


def test_a_clean_file_is_blocked_only_by_the_unverified_layout_until_the_demo_opens_that_gate(shop, monkeypatch):  # noqa: F811
    run_id = stage(shop, [good("INV-1"), good("INV-2")])
    out = check(shop, run_id)
    assert out.status_code == 200 and codes(out) == ["profile_not_verified"] and not out.json()["can_confirm"]
    monkeypatch.setenv("DEMO_READERS", "1")
    out = check(shop, run_id)
    assert out.json()["can_confirm"] and out.json()["included"] == 2 and out.json()["blockers"] == []


def test_the_demo_flag_does_nothing_outside_a_debug_environment(shop, monkeypatch):  # noqa: F811
    monkeypatch.setenv("DEMO_READERS", "1")
    monkeypatch.setattr("app.modules.imports.confirm.debug_env", lambda: False)
    run_id = stage(shop, [good()])
    assert codes(check(shop, run_id)) == ["profile_not_verified"]


def test_held_rows_block_until_each_is_decided_and_a_fix_or_set_aside_clears_it(shop, demo):  # noqa: F811
    pg, biz, _ = shop
    run_id = stage(shop, [good("INV-1"), good("INV-2", hsn=""), good("INV-3", state="Atlantis")])
    out = check(shop, run_id).json()
    assert [(b["code"], b["count"], b["rows"]) for b in out["blockers"]] == [("rows_undecided", 2, [3, 4])]
    by_reason = {r["hold_reason"]: r for r in rows(shop, run_id) if r["status"] == "held"}
    post(pg, f"/api/v1/b/{biz}/rows/{by_reason['blank_hsn']['row_id']}/resolve",
         {"action": "enter_hsn", "note": "Checked the invoice", "value": FULL}, key="k1")
    post(pg, f"/api/v1/b/{biz}/rows/{by_reason['unknown_state']['row_id']}/resolve",
         {"action": "set_aside", "note": "Not ours"}, key="k2")
    out = check(shop, run_id).json()
    assert out["can_confirm"] and out["included"] == 2 and out["left_out"]["set_aside"] == 1


def test_a_short_hsn_blocks_and_a_fix_to_the_full_code_clears_it(shop, demo):  # noqa: F811
    pg, biz, _ = shop
    run_id = stage(shop, [fx.line("INV-1", gstin=GSTIN, hsn="6109")])
    out = check(shop, run_id).json()
    assert [b["code"] for b in out["blockers"]] == ["hsn_too_short"] and out["blockers"][0]["rows"] == [2]
    assert [n["code"] for n in out["notes"]] == ["hsn_band_missing"]  # no turnover band: the stricter count applies


def test_lines_of_one_document_that_disagree_block_and_a_number_reused_in_another_year_does_not(shop, demo):  # noqa: F811
    run_id = stage(shop, [good("INV-1"), good("INV-1", date="04-07-2026")])
    out = check(shop, run_id).json()
    assert [(b["code"], b["rows"]) for b in out["blockers"]] == [("document_rows_disagree", [2, 3])]
    other = stage(shop, [good("INV-1"), good("INV-1", date="03-04-2027", total="999")], name="b.xlsx")
    assert check(shop, other).json()["can_confirm"]


def test_the_answer_carries_no_cell_value_gstin_or_document_number(shop, demo):  # noqa: F811
    run_id = stage(shop, [good("INV-77"), good("INV-77", date="04-07-2026")])
    body = json.dumps(check(shop, run_id).json())
    assert GSTIN not in body and "INV-77" not in body


def test_a_confirmed_or_discarded_run_is_409_and_another_business_or_the_billing_role_is_404(shop, demo):  # noqa: F811
    pg, biz, _ = shop
    run_id = stage(shop, [good()])
    other = new_business(pg, "mallory")
    assert get(pg, f"/api/v1/b/{other}/runs/{run_id}/confirm-check", sub="mallory").status_code == 404
    assert check(shop, run_id, sub="bill").status_code == 404
    assert check(shop, run_id, sub="cathy").status_code == 200 and check(shop, run_id, sub="adam").status_code == 200
    post(pg, f"/api/v1/b/{biz}/runs/{run_id}/discard", key="d1")
    out = check(shop, run_id)
    assert out.status_code == 409 and out.json()["error"]["code"] == "run_not_staged"


def meesho(orders, taxable="170.33898305084747", name="m.zip"):
    return fxa.zipped({"tcs_sales.xlsx": fxm.workbook([fxm.sale(o, gstin=GSTIN, taxable=taxable) for o in orders])})


def test_a_file_that_repeats_a_record_of_another_live_file_with_other_values_clashes_and_may_set_it_aside(shop):  # noqa: F811
    pg, biz, _ = shop
    ids = []
    for name, taxable in (("one.zip", "170.33898305084747"), ("two.zip", "171.5")):
        upload_id, _ = upload(shop, "meesho", name, meesho(["1", "2"], taxable), "application/zip")
        run_jobs(shop)
        ids.append(state(shop, upload_id)["run_id"])
    out = check(shop, ids[1]).json()
    clash = next(b for b in out["blockers"] if b["code"] == "rows_conflict_across_runs")
    assert clash["count"] == 2
    assert "period_date_unconfirmed" in [b["code"] for b in out["blockers"]]  # Flipkart and Meesho wait for CA item 1
    listed = rows(shop, ids[1])
    assert [a["action"] for a in listed[0]["allowed_actions"]] == ["set_aside"]
    for r in listed:
        done = post(pg, f"/api/v1/b/{biz}/rows/{r['row_id']}/resolve", {"action": "set_aside", "note": "Older file is right"},
                    key=f"s{r['row_number']}")
        assert done.status_code == 200
    assert "rows_conflict_across_runs" not in [b["code"] for b in check(shop, ids[1]).json()["blockers"]]


def test_a_new_row_with_no_clash_cannot_be_set_aside(shop):  # noqa: F811
    pg, biz, _ = shop
    upload_id, _ = upload(shop, "meesho", "one.zip", meesho(["1"]), "application/zip")
    run_jobs(shop)
    run_id = state(shop, upload_id)["run_id"]
    row = rows(shop, run_id)[0]
    assert row["allowed_actions"] == []
    out = post(pg, f"/api/v1/b/{biz}/rows/{row['row_id']}/resolve", {"action": "set_aside", "note": "x"}, key="z")
    assert out.status_code == 422 and out.json()["error"]["code"] == "action_not_allowed"


def test_a_blank_key_part_still_clashes_across_files(shop):  # noqa: F811
    """Meesho's order date may be blank in the key; a blank is a value, so two files that both leave it blank
    for the same sub-order but state different amounts still clash (the gate must not miss them)."""
    ids = []
    for name, taxable in (("one.zip", "170.33898305084747"), ("two.zip", "171.5")):
        data = fxa.zipped({"tcs_sales.xlsx": fxm.workbook([fxm.sale("1", gstin=GSTIN, taxable=taxable, order_date="")])})
        upload_id, _ = upload(shop, "meesho", name, data, "application/zip")
        run_jobs(shop)
        ids.append(state(shop, upload_id)["run_id"])
    rows_two = rows(shop, ids[1])
    assert [r["status"] for r in rows_two] == ["new"], rows_two
    blockers = {b["code"]: b for b in check(shop, ids[1]).json()["blockers"]}
    assert blockers["rows_conflict_across_runs"]["count"] == 1
    assert [a["action"] for a in rows_two[0]["allowed_actions"]] == ["set_aside"]
