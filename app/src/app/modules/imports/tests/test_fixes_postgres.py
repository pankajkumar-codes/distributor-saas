"""Value fixes on held rows (R1-M4 slice 4b): enter the HSN of a row that has none, pick the state of a row
whose state is missing. On PostgreSQL through the real Amazon reader and made-up files. Skipped unless
PG_ADMIN_URL is set."""

import uuid

import pytest

from app.modules.imports import readers
from app.modules.imports.readers import register_platform_readers

from .conftest import PG_ADMIN_URL, new_business, scalar
from .fixtures import amazon as fxa
from .test_parse_postgres import GSTIN, state
from .test_uploads_postgres import get, post, run_jobs, shop, upload  # noqa: F401  (the shop fixture)

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")


@pytest.fixture(autouse=True)
def real_readers():
    readers.clear_for_tests()
    register_platform_readers()
    yield
    readers.clear_for_tests()


def fix(shop, row_id, action, note="Checked the invoice", value=None, sub="alice", key=None):  # noqa: F811
    pg, biz, _ = shop
    body = {"action": action, "note": note, **({"value": value} if value is not None else {})}
    return post(pg, f"/api/v1/b/{biz}/rows/{row_id}/resolve", body, sub=sub, key=key or uuid.uuid4().hex)


@pytest.fixture()
def held(shop):  # noqa: F811
    """The rows of a staged Amazon preview that are held for a blank HSN and a blank state."""
    pg, biz, _ = shop
    z = fxa.zipped({"MTR_B2C-JUL-2026.csv": fxa.b2c_held(gstin=GSTIN)})
    upload_id, _ = upload(shop, "amazon", "july.zip", z, "application/zip")
    run_jobs(shop)
    run_id = state(shop, upload_id)["run_id"]
    rows = get(pg, f"/api/v1/b/{biz}/runs/{run_id}/rows?status=held").json()["rows"]
    return {r["hold_reason"]: r for r in rows}, run_id


def test_a_row_with_no_hsn_offers_enter_hsn_and_a_row_with_no_state_offers_pick_state(held):
    rows, _ = held
    assert [a["action"] for a in rows["blank_hsn"]["allowed_actions"]] == ["set_aside", "enter_hsn"]
    assert [a["action"] for a in rows["unknown_state"]["allowed_actions"]] == ["set_aside", "pick_state"]
    assert [a["action"] for a in rows["blank_qty"]["allowed_actions"]] == ["set_aside"]


def test_an_hsn_is_entered_and_kept_beside_the_row_and_the_counts_follow(shop, held):  # noqa: F811
    pg, biz, _ = shop
    rows, run_id = held
    out = fix(shop, rows["blank_hsn"]["row_id"], "enter_hsn", value="6109")
    assert out.status_code == 200
    resolution = out.json()["resolution"]
    assert resolution["action"] == "enter_hsn" and resolution["value"] == "6109" and out.json()["allowed_actions"] == []
    assert out.json()["values"]["Hsn/sac"] == ""  # the row as the file said it is not changed
    run = get(pg, f"/api/v1/b/{biz}/runs/{run_id}").json()
    assert run["counts"]["fixed"] == 1 and "blank_hsn" not in run["held_by_reason"]
    assert scalar(pg.owner, "select count(*) from imports.row_resolutions where kind = 'fixed' and fix_field = 'hsn'") == 1


def test_a_state_is_picked_from_the_state_list(shop, held):  # noqa: F811
    rows, _ = held
    row = rows["unknown_state"]["row_id"]
    assert fix(shop, row, "pick_state", value="Narnia").json()["error"]["code"] == "state_unknown"
    done = fix(shop, row, "pick_state", value="19")
    assert done.status_code == 200 and done.json()["resolution"]["value"] == "19"


@pytest.mark.parametrize("value, code", [(None, "value_required"), ("  ", "value_required"),
                                         ("61 09", "hsn_invalid"), ("61a9", "hsn_invalid"), ("123", "hsn_invalid")])
def test_a_bad_hsn_is_refused_with_nothing_recorded(shop, held, value, code):  # noqa: F811
    pg, _, _ = shop
    rows, _ = held
    out = fix(shop, rows["blank_hsn"]["row_id"], "enter_hsn", value=value)
    assert out.status_code == 422 and out.json()["error"]["code"] == code
    assert scalar(pg.owner, "select count(*) from imports.row_resolutions") == 0


def test_a_fix_needs_a_note_and_only_fits_its_own_hold_reason(shop, held):  # noqa: F811
    rows, _ = held
    assert fix(shop, rows["blank_hsn"]["row_id"], "enter_hsn", note=" ", value="6109").json()["error"]["code"] == "note_required"
    assert fix(shop, rows["blank_hsn"]["row_id"], "pick_state", value="19").json()["error"]["code"] == "action_not_allowed"
    assert fix(shop, rows["blank_qty"]["row_id"], "enter_hsn", value="6109").json()["error"]["code"] == "action_not_allowed"


def test_the_same_fix_twice_is_one_decision_and_a_different_value_is_refused(shop, held):  # noqa: F811
    pg, _, _ = shop
    rows, _ = held
    row = rows["blank_hsn"]["row_id"]
    assert fix(shop, row, "enter_hsn", value="6109", key="k-1").status_code == 200
    assert fix(shop, row, "enter_hsn", value="6109", key="k-1").status_code == 200  # same key
    assert fix(shop, row, "enter_hsn", value="6109").status_code == 200  # same decision, no new row
    assert fix(shop, row, "enter_hsn", value="6110").json()["error"]["code"] == "action_not_allowed"
    assert fix(shop, row, "set_aside").json()["error"]["code"] == "action_not_allowed"
    assert scalar(pg.owner, "select count(*) from imports.row_resolutions") == 1


def test_the_audit_names_the_field_and_never_the_value(shop, held):  # noqa: F811
    pg, _, _ = shop
    rows, _ = held
    fix(shop, rows["blank_hsn"]["row_id"], "enter_hsn", value="6109")
    data = scalar(pg.owner, "select data::text from platform.audit_log where action = 'imports.row_fixed'")
    assert '"field": "hsn"' in data and "6109" not in data


def test_only_the_uploaders_may_fix_and_another_business_gets_404(shop, held):  # noqa: F811
    pg, _, _ = shop
    rows, _ = held
    row = rows["blank_hsn"]["row_id"]
    other = new_business(pg, "bob")
    assert post(pg, f"/api/v1/b/{other}/rows/{row}/resolve", {"action": "enter_hsn", "note": "x", "value": "6109"},
                sub="bob", key="k-bob").status_code == 404
    assert scalar(pg.owner, "select count(*) from imports.row_resolutions") == 0
