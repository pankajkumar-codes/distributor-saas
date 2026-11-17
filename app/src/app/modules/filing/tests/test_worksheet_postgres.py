"""The GSTR-3B worksheet on PostgreSQL (R1-M8b, W2): build, versions, entries, gate, plan, tenant and role.

The GSTR-1 build and its checks are staged (as in the export tests); what is real is the route, the tables, the audit rows,
the lock that numbers versions, the entitlement hook and row-level security.
"""

import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.modules.filing import api_worksheet, entitlement, worksheet
from app.modules.filing.checks import Finding
from platform_common import jobs, render
from platform_common.queue import FakeQueue, set_queue
from platform_common.storage import LocalObjectStore, get_store, key_for, set_store

from .conftest import PG_ADMIN_URL, as_user, ctx, new_business, scalar, seed_member, user_id
from .test_gstr1_sections import CN, INV, KA, SOAP, TEA, WB, A, I3, line
from .test_periods_postgres import choose
from .test_snapshots_postgres import build_of

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")
D = Decimal


def sales():
    return [
        line("INV-1", 5, INV, "B2B", WB, SOAP, "10", "1000.00", cgst="90.00", sgst="90.00", value="1180.00", buyer=A),
        line("INV-2", 6, INV, "B2CS", KA, TEA, "2", "200.00", igst="10.00", value="210.00"),
        line("CN-1", 7, CN, "CDNR", WB, SOAP, "1", "100.00", cgst="9.00", sgst="9.00", value="118.00", buyer=A,
             original=("INV-1", I3)),
    ]  # fmt: skip


class Stage:
    def __init__(self):
        self.lines = sales()
        self.fp = "a" * 64
        self.findings = []

    def build(self, tx, inst):
        return build_of(inst, self.lines, self.fp)

    def checks(self, tx, b):
        return list(self.findings)


@pytest.fixture()
def ws(pg, monkeypatch, tmp_path):
    from app import api as app_api
    from platform_common.clock import IST, FrozenClock, get_clock

    app_api.app.dependency_overrides[get_clock] = lambda: FrozenClock(datetime(2026, 11, 15, 12, 0, tzinfo=IST))
    jobs_q, render_q = FakeQueue(), FakeQueue()
    set_queue(jobs_q)
    render.set_render_queue(render_q)
    set_store(LocalObjectStore(tmp_path))
    pg.jobs_q, pg.render_q = jobs_q, render_q
    stage = Stage()
    for mod in (worksheet, api_worksheet):
        monkeypatch.setattr(mod, "build_return", stage.build, raising=False)
    monkeypatch.setattr(worksheet, "run_checks", stage.checks)
    b = new_business(pg, "alice")
    choose(pg, b, "monthly")
    rows = pg.client.get(f"/api/v1/b/{b}/returns", params={"fy": "2026-27"}, headers=as_user("alice")).json()["returns"]
    g3 = next(x["instance_id"] for x in rows if x["form"] == "GSTR3B" and x["period"] == "2026-10")
    g1 = next(x["instance_id"] for x in rows if x["form"] == "GSTR1" and x["period"] == "2026-10")
    try:
        yield pg, b, g3, g1, stage
    finally:
        entitlement.set_check(None)
        set_store(None)
        set_queue(None)
        render.set_render_queue(None)


def url(b, inst, tail=""):
    return f"/api/v1/b/{b}/returns/{inst}/worksheet{tail}"


def get(pg, b, inst, sub="alice"):
    return pg.client.get(url(b, inst), headers=as_user(sub))


def build(pg, b, inst, sub="alice"):
    return pg.client.post(url(b, inst, "/build"), headers=as_user(sub))


def put(pg, b, inst, entries, based_on=None, sub="alice"):
    return pg.client.put(url(b, inst, "/entries"), json={"entries": entries, "based_on_seq": based_on}, headers=as_user(sub))


def code(r):
    return r.json()["error"]["code"]


def test_build_gives_the_gstr1_outward_figures_and_a_version(ws):
    pg, b, g3, g1, stage = ws
    assert get(pg, b, g3).json()["built"] is False
    r = build(pg, b, g3)
    assert r.status_code == 200, r.text
    o = r.json()
    assert o["version"] == 1
    assert o["taxable"] == {"taxable_value": "1100.00", "igst": "10.00", "cgst": "81.00", "sgst": "81.00", "cess": "0.00"}
    assert [(x["pos_state_code"], x["unregistered_taxable"]) for x in o["inter_state"]] == [("29", "200.00")]
    assert {f["code"] for f in o["flags"]} >= {"note_netting", "nil_exempt_non_gst_not_built"}
    assert scalar(pg.owner, "select count(*) from platform.audit_log where action = 'worksheet.built'") == 1


def test_building_again_for_an_unchanged_gstr1_writes_nothing_new(ws):
    pg, b, g3, g1, stage = ws
    build(pg, b, g3)
    again = build(pg, b, g3)
    assert again.status_code == 200 and again.json()["version"] == 1
    assert scalar(pg.owner, "select count(*) from filing.worksheet_versions") == 1
    assert scalar(pg.owner, "select count(*) from platform.audit_log where action = 'worksheet.built'") == 1


def test_out_of_date_then_rebuild_is_a_new_version_and_entries_survive(ws):
    pg, b, g3, g1, stage = ws
    build(pg, b, g3)
    assert put(pg, b, g3, {"t4a.other.igst": "50"}).status_code == 200
    assert get(pg, b, g3).json()["out_of_date"] is False
    stage.lines = stage.lines[:1]
    stage.fp = "b" * 64
    w = get(pg, b, g3).json()
    assert w["out_of_date"] is True and w["outward"]["version"] == 1
    r = build(pg, b, g3)
    assert r.json()["version"] == 2 and r.json()["taxable"]["taxable_value"] == "1000.00"
    w = get(pg, b, g3).json()
    assert w["out_of_date"] is False and w["entries"] == {"t4a.other.igst": "50.00"}


def test_an_unresolved_block_refuses_the_build(ws):
    pg, b, g3, g1, stage = ws
    stage.findings = [Finding("C-01", "block", "INV-1: HSN is missing.", ("INV-1",), "x" * 8, False)]
    r = build(pg, b, g3)
    assert r.status_code == 409 and code(r) == "worksheet_blocked"
    w = get(pg, b, g3).json()
    assert w["can_build"] is False and "1 item" in w["build_blocked_by"]
    assert scalar(pg.owner, "select count(*) from filing.worksheet_versions") == 0
    stage.findings = [Finding("C-04", "warn", "x", ("INV-1",), "y" * 8, False)]  # a warning does not stop it
    assert build(pg, b, g3).status_code == 200


def test_two_builds_at_once_number_versions_without_a_gap_or_a_duplicate(ws):
    pg, b, g3, g1, stage = ws
    def one(i):
        stage.fp = f"{i:x}".rjust(64, "c")
        return build(pg, b, g3).status_code

    with ThreadPoolExecutor(4) as ex:
        assert list(ex.map(one, range(4))) == [200] * 4
    versions = sorted(r[0] for r in pg.owner.connect().execute(text("select version from filing.worksheet_versions")))
    assert versions == list(range(1, len(versions) + 1))


def test_entries_are_saved_one_row_per_change_and_audited_by_field_name(ws):
    pg, b, g3, g1, stage = ws
    r = put(pg, b, g3, {"t4a.other.cgst": "100", "t4b.rev_other.igst": "1,250.5"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["entries_seq"] == 1
    assert body["entries"] == {"t4a.other.cgst": "100.00", "t4a.other.sgst": "100.00", "t4b.rev_other.igst": "1250.50"}
    assert body["net_itc"] == {"igst": "-1250.50", "cgst": "100.00", "sgst": "100.00", "cess": "0.00"}
    same = put(pg, b, g3, {"t4a.other.cgst": "100.00", "t4b.rev_other.igst": "1250.5"}, based_on=1)
    assert same.json()["entries_seq"] == 1  # a retry writes nothing
    assert scalar(pg.owner, "select count(*) from filing.worksheet_entries") == 1
    r2 = put(pg, b, g3, {"t4a.other.cgst": "120"}, based_on=1)
    assert r2.json()["entries_seq"] == 2
    rows = pg.owner.connect().execute(text("select seq, previous_seq, entry from filing.worksheet_entries order by seq")).all()
    assert [(r[0], r[1]) for r in rows] == [(1, None), (2, 1)]
    assert rows[0][2]["t4b.rev_other.igst"] == "1250.50"  # the old values stay readable
    audit = pg.owner.connect().execute(
        text("select data from platform.audit_log where action = 'worksheet.entered' order by at")
    ).all()
    assert audit[1][0]["fields"] == ["t4a.other.cgst", "t4a.other.sgst", "t4b.rev_other.igst"]
    assert "120" not in json.dumps([a[0] for a in audit])  # no amounts in the audit row


def test_a_stale_save_is_refused(ws):
    pg, b, g3, g1, stage = ws
    put(pg, b, g3, {"t4a.other.igst": "1"})
    r = put(pg, b, g3, {"t4a.other.igst": "2"}, based_on=None)
    assert r.status_code == 409 and code(r) == "worksheet_changed"


@pytest.mark.parametrize(
    "entries, field",
    [
        ({"t4a.other.igst": "-1"}, "t4a.other.igst"),
        ({"t4a.other.igst": "1.234"}, "t4a.other.igst"),
        ({"t4a.other.igst": "abc"}, "t4a.other.igst"),
        ({"t4a.other.sgst": "5"}, "t4a.other.sgst"),  # state/UT tax without central tax
        ({"t4a.other.cgst": "5", "t4a.other.sgst": "6"}, "t4a.other.sgst"),  # the two must be equal
        ({"t9.nothing.igst": "1"}, "t9.nothing.igst"),
        ({"t4a.import_goods.cgst": "1"}, "t4a.import_goods.cgst"),  # no such column on that row
    ],
)
def test_bad_entries_are_refused_with_the_field(ws, entries, field):
    pg, b, g3, g1, stage = ws
    r = put(pg, b, g3, entries)
    assert r.status_code == 422 and code(r) == "invalid_entry" and r.json()["error"]["field"] == field
    assert scalar(pg.owner, "select count(*) from filing.worksheet_entries") == 0


def test_a_float_is_refused(ws):
    pg, b, g3, g1, stage = ws
    assert put(pg, b, g3, {"t4a.other.igst": 1.5}).status_code == 422


def test_not_allowed_by_the_plan_gives_no_figures(ws):
    pg, b, g3, g1, stage = ws
    build(pg, b, g3)
    put(pg, b, g3, {"t4a.other.igst": "7"})
    entitlement.set_check(lambda tx, business: False)
    w = get(pg, b, g3)
    assert w.status_code == 200
    j = w.json()
    assert j["available"] is False and j["built"] is True and j["outward"] is None and j["entries"] == {}
    assert build(pg, b, g3).status_code == 409 and code(build(pg, b, g3)) == "worksheet_not_available"
    assert put(pg, b, g3, {"t4a.other.igst": "8"}, based_on=1).status_code == 409


def test_it_is_never_a_filing_and_never_a_net_payable(ws):
    pg, b, g3, g1, stage = ws
    build(pg, b, g3)
    put(pg, b, g3, {"t4a.other.igst": "7"})
    body = get(pg, b, g3).json()
    assert body["label"] == "Worksheet, not a filing"

    def keys(x):
        if isinstance(x, dict):
            for k, v in x.items():
                yield k
                yield from keys(v)
        elif isinstance(x, list):
            for v in x:
                yield from keys(v)

    assert not [k for k in keys(body) if any(w in k.lower() for w in ("payable", "offset_amount", "net_tax", "liability"))]
    blob = json.dumps(body).lower()
    assert "filed" not in blob.replace("not a filing", "") and "ready to file" not in blob


def test_other_businesses_other_forms_and_unknown_ids_are_404(ws):
    pg, b, g3, g1, stage = ws
    other = new_business(pg, "bob")
    assert get(pg, other, g3, "bob").status_code == 404  # another business's instance
    assert get(pg, b, g3, "bob").status_code == 404  # not a member
    assert build(pg, other, g3, "bob").status_code == 404
    assert put(pg, other, g3, {"t4a.other.igst": "1"}, sub="bob").status_code == 404
    assert get(pg, b, g1).status_code == 404  # a GSTR-1 is not a worksheet
    assert get(pg, b, uuid.uuid4()).status_code == 404 and get(pg, b, "nope").status_code == 404
    assert scalar(pg.owner, "select count(*) from filing.worksheet_entries") == 0


def test_a_billing_member_has_no_access_and_a_ca_can_prepare(ws):
    pg, b, g3, g1, stage = ws
    seed_member(pg, b, "bill", "billing")
    seed_member(pg, b, "carol", "ca")
    assert get(pg, b, g3, "bill").status_code == 404
    assert build(pg, b, g3, "bill").status_code == 404
    assert build(pg, b, g3, "carol").status_code == 200


def test_the_tables_refuse_update_delete_and_truncate(ws):
    pg, b, g3, g1, stage = ws
    build(pg, b, g3)
    put(pg, b, g3, {"t4a.other.igst": "1"})
    uid = user_id(pg.owner, "alice")
    for sql in (
        "update filing.worksheet_versions set flags = '[]'",
        "delete from filing.worksheet_versions",
        "update filing.worksheet_entries set entry = '{}'",
        "delete from filing.worksheet_entries",
        "truncate filing.worksheet_entries",
    ):
        with pytest.raises(DBAPIError), pg.app_rw.begin() as c:
            ctx(c, uid, b)
            c.execute(text(sql))


def test_another_tenant_sees_no_rows_through_the_database(ws):
    pg, b, g3, g1, stage = ws
    build(pg, b, g3)
    other = new_business(pg, "bob")
    with pg.app_rw.begin() as c:
        ctx(c, user_id(pg.owner, "bob"), other)
        assert c.execute(text("select count(*) from filing.worksheet_versions")).scalar() == 0
        with pytest.raises(DBAPIError):
            c.execute(
                text(
                    "insert into filing.worksheet_versions (id, business_id, instance_id, version, build_fingerprint, outward)"
                    " values (gen_random_uuid(), :b, :i, 9, :f, '{}')"
                ),
                {"b": b, "i": g3, "f": "a" * 64},
            )


def read_book(pg, b, version=1, seq=0):
    from io import BytesIO

    from openpyxl import load_workbook

    vid = scalar(pg.owner, "select id from filing.worksheet_versions where version = :v", v=version)
    data = get_store().get_bytes(b, key_for(b, "exports", vid, f"v{version}-e{seq}.xlsx"))
    return load_workbook(BytesIO(data))


def test_the_excel_file_equals_the_screen_to_the_paisa_and_holds_no_formula(ws):
    pg, b, g3, g1, stage = ws
    assert pg.client.get(url(b, g3, "/excel"), headers=as_user("alice")).status_code == 409  # nothing built
    build(pg, b, g3)
    put(pg, b, g3, {"t4a.other.cgst": "100", "t4b.rev_other.igst": "1,250.5"})
    r = pg.client.get(url(b, g3, "/excel"), headers=as_user("alice"))
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["version"] == 1 and j["entries_seq"] == 1 and j["out_of_date"] is False and j["name"].endswith(".xlsx")
    assert j["url"].startswith("/api/v1/dev/objects")
    wb = read_book(pg, b, seq=1)
    ws1 = wb["GSTR-3B"]
    cells = [c for row in ws1.iter_rows() for c in row if c.value is not None]
    assert all(c.data_type != "f" for c in cells)
    screen = get(pg, b, g3).json()
    nums = [Decimal(str(c.value)) for c in cells if isinstance(c.value, (int, float))]
    for v in (*screen["outward"]["taxable"].values(), *screen["entries"].values(), *screen["net_itc"].values()):
        assert Decimal(v) in nums
    assert ws1["A1"].value == "Worksheet, not a filing"
    text_blob = " ".join(str(c.value) for c in cells).lower()
    assert "payable" not in text_blob and "ready to file" not in text_blob
    assert "offset and payment are done on the gst portal." in text_blob
    assert {r[1].value for r in wb["Sources"].iter_rows(min_row=3)} >= {"INV-1", "CN-1"}


def test_a_document_number_that_looks_like_a_formula_stays_text(ws):
    pg, b, g3, g1, stage = ws
    stage.lines = [line("=HYPERLINK(1)", 5, INV, "B2CS", WB, SOAP, "1", "100.00", cgst="9.00", sgst="9.00", value="118.00")]
    build(pg, b, g3)
    pg.client.get(url(b, g3, "/excel"), headers=as_user("alice"))
    sources = read_book(pg, b)["Sources"]
    cell = next(c for row in sources.iter_rows() for c in row if c.value == "=HYPERLINK(1)")
    assert cell.data_type == "s"


def test_the_excel_says_when_it_is_out_of_date_and_is_closed_when_the_plan_says_no(ws):
    pg, b, g3, g1, stage = ws
    build(pg, b, g3)
    stage.fp = "b" * 64
    j = pg.client.get(url(b, g3, "/excel"), headers=as_user("alice")).json()
    assert j["out_of_date"] is True
    first = read_book(pg, b)["GSTR-3B"]
    assert any(str(c.value).startswith("Out of date") for row in first.iter_rows() for c in row)
    entitlement.set_check(lambda tx, business: False)
    assert pg.client.get(url(b, g3, "/excel"), headers=as_user("alice")).status_code == 409


def test_the_excel_route_is_tenant_and_role_scoped(ws):
    pg, b, g3, g1, stage = ws
    build(pg, b, g3)
    new_business(pg, "bob")
    seed_member(pg, b, "bill", "billing")
    assert pg.client.get(url(b, g3, "/excel"), headers=as_user("bob")).status_code == 404
    assert pg.client.get(url(b, g3, "/excel"), headers=as_user("bill")).status_code == 404
    assert pg.client.get(url(b, g1, "/excel"), headers=as_user("alice")).status_code == 404


def rows_url(b, inst, **q):
    from urllib.parse import urlencode

    return url(b, inst, "/rows") + "?" + urlencode(q)


def test_drill_down_rows_sum_to_the_built_figures(ws):
    pg, b, g3, g1, stage = ws
    built = build(pg, b, g3).json()
    r = pg.client.get(rows_url(b, g3, figure="3_1_a"), headers=as_user("alice"))
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["total"] == built["taxable"] and j["out_of_date"] is False and j["next_cursor"] is None
    assert [(x["section"], x["kind"], x["doc_number"]) for x in j["rows"]][-1] == ("cdnr", "credit_note", "CN-1")
    assert next(x for x in j["rows"] if x["kind"] == "credit_note")["taxable_value"] == "-100.00"
    s = pg.client.get(rows_url(b, g3, figure="3_2", state="29"), headers=as_user("alice")).json()
    assert s["total"]["taxable_value"] == built["inter_state"][0]["unregistered_taxable"]
    assert s["total"]["igst"] == built["inter_state"][0]["unregistered_igst"]


def test_drill_down_says_out_of_date_and_refuses_bad_asks(ws):
    pg, b, g3, g1, stage = ws
    build(pg, b, g3)
    stage.fp = "b" * 64
    assert pg.client.get(rows_url(b, g3, figure="3_1_a"), headers=as_user("alice")).json()["out_of_date"] is True
    for q in ({"figure": "3_2"}, {"figure": "3_1_a", "state": "29"}, {"figure": "9"}, {"figure": "3_2", "state": "x"},
              {"figure": "3_1_a", "cursor": "-1"}, {"figure": "3_1_a", "cursor": "z"}):  # fmt: skip
        assert pg.client.get(rows_url(b, g3, **q), headers=as_user("alice")).status_code == 422, q


def test_drill_down_pages(ws, monkeypatch):
    from app.modules.filing import api_worksheet

    pg, b, g3, g1, stage = ws
    monkeypatch.setattr(api_worksheet, "PAGE", 2)
    first = pg.client.get(rows_url(b, g3, figure="3_1_a"), headers=as_user("alice")).json()
    assert len(first["rows"]) == 2 and first["next_cursor"] == "2"
    second = pg.client.get(rows_url(b, g3, figure="3_1_a", cursor="2"), headers=as_user("alice")).json()
    assert len(second["rows"]) == 1 and second["next_cursor"] is None
    assert first["total"] == second["total"]


def test_drill_down_is_tenant_role_and_plan_scoped(ws):
    pg, b, g3, g1, stage = ws
    new_business(pg, "bob")
    seed_member(pg, b, "bill", "billing")
    for sub in ("bob", "bill"):
        assert pg.client.get(rows_url(b, g3, figure="3_1_a"), headers=as_user(sub)).status_code == 404
    assert pg.client.get(rows_url(b, g1, figure="3_1_a"), headers=as_user("alice")).status_code == 404
    entitlement.set_check(lambda tx, business: False)
    assert pg.client.get(rows_url(b, g3, figure="3_1_a"), headers=as_user("alice")).status_code == 409


# -- PDF (W5b) ----------------------------------------------------------------------------------------------------------


def start_pdf(pg, b, inst, sub="alice"):
    return pg.client.post(url(b, inst, "/pdf"), headers=as_user(sub))


def pdf_status(pg, b, inst, job, sub="alice"):
    return pg.client.get(url(b, inst, f"/pdf/{job}"), headers=as_user(sub))


def test_the_pdf_is_queued_rendered_from_the_screen_figures_and_linked(ws):
    pg, b, g3, g1, stage = ws
    assert start_pdf(pg, b, g3).status_code == 409  # nothing built yet
    build(pg, b, g3)
    put(pg, b, g3, {"t4a.other.cgst": "100"})
    r = start_pdf(pg, b, g3)
    assert r.status_code == 202, r.text
    job = r.json()["job_id"]
    assert start_pdf(pg, b, g3).json()["job_id"] == job  # the same state joins the same job
    assert pdf_status(pg, b, g3, job).json()["status"] == "queued"
    assert pg.jobs_q.drain(jobs.handle_message) == [jobs.DONE]
    assert pg.render_q.sent == [{"key": f"render-input/b/{b}/{job}/input.json"}]
    doc = json.loads(get_store().get_bytes(b, f"render-input/b/{b}/{job}/input.json"))
    assert doc["template"] == "gstr3b-worksheet" and doc["label"] == "Worksheet, not a filing" and doc["banner"] is None
    screen = get(pg, b, g3).json()
    rows = {r["label"]: r["cells"] for s in doc["sections"] for r in s["rows"]}
    assert rows["(a) Outward Taxable supplies (other than zero rated, nil rated and exempted)"] == [
        screen["outward"]["taxable"][h] for h in ("taxable_value", "igst", "cgst", "sgst", "cess")
    ]
    assert rows["(5) All other ITC"] == ["", "100.00", "100.00", ""]
    assert rows["(C) Net ITC Available (A)-(B)"] == [screen["net_itc"][h] for h in ("igst", "cgst", "sgst", "cess")]
    blob = json.dumps(doc).lower()
    assert "payable" not in blob and "ready to file" not in blob and "offset and payment are done on the gst portal" in blob
    assert pdf_status(pg, b, g3, job).json()["status"] == "rendering"
    get_store().put(b, f"documents/b/{b}/{job}/document.pdf", b"%PDF-", "application/pdf")
    done = pdf_status(pg, b, g3, job).json()
    assert done["status"] == "ready" and done["url"].startswith("/api/v1/dev/objects")


def test_a_pdf_job_for_an_old_state_fails_and_a_new_request_gets_a_new_job(ws):
    pg, b, g3, g1, stage = ws
    build(pg, b, g3)
    job = start_pdf(pg, b, g3).json()["job_id"]
    put(pg, b, g3, {"t4a.other.igst": "5"})  # saved after the job was queued
    assert pg.jobs_q.drain(jobs.handle_message) == [jobs.FAILED]
    assert pg.render_q.sent == []
    assert pdf_status(pg, b, g3, job).json() == {"status": "failed", "url": None, "error_code": "changed"}
    again = start_pdf(pg, b, g3).json()["job_id"]
    assert again != job  # a different state, so a different job
    assert pg.jobs_q.drain(jobs.handle_message) == [jobs.DONE]


def test_a_failed_pdf_job_does_not_lock_the_user_out(ws):
    pg, b, g3, g1, stage = ws
    build(pg, b, g3)
    first = start_pdf(pg, b, g3).json()["job_id"]
    entitlement.set_check(lambda tx, business: False)  # the plan closes before the job runs
    assert pg.jobs_q.drain(jobs.handle_message) == [jobs.FAILED]
    entitlement.set_check(None)
    second = start_pdf(pg, b, g3).json()["job_id"]
    assert second != first
    assert pg.jobs_q.drain(jobs.handle_message) == [jobs.DONE]


def test_the_pdf_routes_are_tenant_role_and_plan_scoped(ws):
    pg, b, g3, g1, stage = ws
    build(pg, b, g3)
    job = start_pdf(pg, b, g3).json()["job_id"]
    new_business(pg, "bob")
    seed_member(pg, b, "bill", "billing")
    for sub in ("bob", "bill"):
        assert start_pdf(pg, b, g3, sub).status_code == 404
        assert pdf_status(pg, b, g3, job, sub).status_code == 404
    assert start_pdf(pg, b, g1).status_code == 404
    assert pdf_status(pg, b, g3, uuid.uuid4()).status_code == 404
    assert pdf_status(pg, b, g3, "nope").status_code == 404
    entitlement.set_check(lambda tx, business: False)
    assert start_pdf(pg, b, g3).status_code == 409
