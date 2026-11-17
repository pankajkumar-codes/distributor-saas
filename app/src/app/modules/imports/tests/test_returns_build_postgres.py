"""R1-M7 slice 5: GET /returns/{instance} and /sections/{section} over a build from confirmed uploaded invoices, through the
real API on PostgreSQL. Skipped unless PG_ADMIN_URL is set."""

import uuid
from decimal import Decimal

import pytest

from .conftest import PG_ADMIN_URL, new_business
from .test_build_postgres import get, post, shop  # noqa: F401
from .test_confirm_postgres import confirm, line, month, monthly, real_readers, stage  # noqa: F401

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")


def instances(shop):  # noqa: F811
    pg, biz, _ = shop
    out = get(pg, f"/api/v1/b/{biz}/returns?fy=2026-27")
    assert out.status_code == 200, out.text
    return {r["form"]: r["instance_id"] for r in out.json()["returns"] if r["period"] == "2026-10"}


def confirmed_month(shop):  # noqa: F811
    monthly(shop)
    assert confirm(shop, stage(shop, month(shop))).status_code == 200
    return instances(shop)["GSTR1"]


def test_a_confirmed_month_shows_totals_findings_flags_and_a_draft_banner(shop):  # noqa: F811
    pg, biz, _ = shop
    inst = confirmed_month(shop)
    r = get(pg, f"/api/v1/b/{biz}/returns/{inst}")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["instance"]["instance_id"] == inst and d["instance"]["form"] == "GSTR1"
    assert d["draft"] is True and d["banner"].startswith("Draft") and d["report_only"] is True
    assert Decimal(d["totals"]["liability"]["taxable_value"]) == 650 and Decimal(d["totals"]["liability"]["igst"]) == 36
    assert all(Decimal(v) == 0 for v in d["totals"]["gap"].values())  # Table 12 agrees with the liability tables
    assert {s["name"]: s["rows_count"] for s in d["sections"]}["b2b"] == 1
    assert d["debit_notes"]["count"] == 1 and "not in this return yet" in d["debit_notes"]["notice"]
    flags = {f["code"] for f in d["ca_flags"]}
    assert {"debit_notes_unsummed", "marketplace_reports", "uqc_mapping"} <= flags
    assert "C-16" in {g["code"] for g in d["finding_groups"]}
    assert len(d["fingerprint"]) == 64 and d["members_count"] == 4  # four documents; the debit note is not a member
    again = get(pg, f"/api/v1/b/{biz}/returns/{inst}").json()
    assert again["fingerprint"] == d["fingerprint"]  # reading changes nothing


def test_a_section_lists_its_rows_with_source_references_and_exact_amounts(shop):  # noqa: F811
    pg, biz, _ = shop
    inst = confirmed_month(shop)
    r = get(pg, f"/api/v1/b/{biz}/returns/{inst}/sections/b2b")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["has_more"] is False and d["next_cursor"] is None and len(d["rows"]) == 1
    row = d["rows"][0]
    assert row["invoice_number"] == "INV-3" and Decimal(row["taxable_value"]) == 200 and Decimal(row["cgst"]) == 18
    assert row["source_refs"] and all(s.startswith("a.xlsx row ") for s in row["source_refs"])
    assert "recipient_gstin" in row
    hsn = get(pg, f"/api/v1/b/{biz}/returns/{inst}/sections/hsn_b2c").json()["rows"]
    assert hsn and all(h["source_refs"] for h in hsn)


def test_bad_section_cursor_and_ids_are_refused(shop):  # noqa: F811
    pg, biz, _ = shop
    inst = confirmed_month(shop)
    assert get(pg, f"/api/v1/b/{biz}/returns/{inst}/sections/nope").status_code == 404
    bad = get(pg, f"/api/v1/b/{biz}/returns/{inst}/sections/b2b?cursor=abc")
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "invalid_cursor"
    assert get(pg, f"/api/v1/b/{biz}/returns/not-a-uuid").status_code == 404
    assert get(pg, f"/api/v1/b/{biz}/returns/{uuid.uuid4()}").status_code == 404


def test_only_prepare_roles_read_a_return_and_another_business_gets_404(shop):  # noqa: F811
    pg, biz, _ = shop
    inst = confirmed_month(shop)
    path = f"/api/v1/b/{biz}/returns/{inst}"
    assert get(pg, path, sub="adam").status_code == 200  # admin
    assert get(pg, path, sub="cathy").status_code == 200  # CA
    assert get(pg, path, sub="bill").status_code == 404  # billing
    assert get(pg, path, sub="mallory").status_code == 404  # not a member at all
    other = new_business(pg, "mallory")
    assert get(pg, f"/api/v1/b/{other}/returns/{inst}", sub="mallory").status_code == 404  # an id from another business
    assert get(pg, f"/api/v1/b/{other}/returns/{inst}/sections/b2b", sub="mallory").status_code == 404


def test_a_return_that_is_not_built_from_supply_lines_is_404(shop):  # noqa: F811
    pg, biz, _ = shop
    confirmed_month(shop)
    forms = instances(shop)
    assert "GSTR3B" in forms
    assert get(pg, f"/api/v1/b/{biz}/returns/{forms['GSTR3B']}").status_code == 404
