"""R1-M7 slice 4: the checks over a build from confirmed uploaded invoices (report-only). On PostgreSQL through the real
reader and confirm. Skipped unless PG_ADMIN_URL is set."""

import pytest
from sqlalchemy.orm import Session

from app.modules.filing.interface import build_return, run_checks

from .conftest import PG_ADMIN_URL, ctx, scalar, user_id
from .test_build_postgres import built, get, shop  # noqa: F401
from .test_confirm_postgres import OCT, confirm, line, month, monthly, real_readers, stage  # noqa: F401
from .test_parse_postgres import GSTIN

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")


def findings(shop, rows):  # noqa: F811
    monthly(shop)
    run_id = stage(shop, rows)
    out = confirm(shop, run_id)
    assert out.status_code == 200, (out.text, get(shop[0], f"/api/v1/b/{shop[1]}/runs/{run_id}/confirm-check").json()["blockers"])
    pg, biz, _ = shop
    with pg.app_rw.begin() as c:
        ctx(c, user_id(pg.owner, "alice"), biz)
        tx = Session(bind=c)
        return run_checks(tx, built_in(tx, shop))


def built_in(tx, shop):  # noqa: F811
    from datetime import date

    from app.modules.filing.interface import instances_between

    inst = [i for i in instances_between(tx, GSTIN, date(2026, 10, 1), date(2026, 10, 31)) if i.form == "GSTR1"][0]
    return build_return(tx, inst)


def codes(fs):
    return sorted({f.code for f in fs})


def test_a_clean_invoice_has_only_the_standing_unconfirmed_values_finding(shop):  # noqa: F811
    fs = findings(shop, [line("INV-1")])
    assert codes(fs) == ["C-16"] and fs[0].level == "warn" and fs[0].needs_ca_check
    assert "invoice.number.max_length" in fs[0].message


def test_a_tax_that_is_not_taxable_times_rate_is_shown_with_the_difference_never_blocked(shop):  # noqa: F811
    fs = findings(shop, [line("INV-1", cgst="10", sgst="10", total="220")])
    arithmetic = [f for f in fs if f.code == "A-01"]
    assert len(arithmetic) == 1 and "difference -16" in arithmetic[0].message
    assert arithmetic[0].level == "warn" and arithmetic[0].needs_ca_check
    assert arithmetic[0].source_refs and arithmetic[0].source_refs[0].startswith("a.xlsx row ")


def test_heads_that_do_not_fit_the_place_of_supply_are_reported(shop):  # noqa: F811
    fs = findings(shop, [line("INV-1", state="Karnataka")])  # CGST and SGST on a supply outside the seller's state
    assert "A-02" in codes(fs)


def findings_in_new_month(shop):  # noqa: F811
    pg, biz, _ = shop
    with pg.app_rw.begin() as c:
        ctx(c, user_id(pg.owner, "alice"), biz)
        tx = Session(bind=c)
        return run_checks(tx, built_in(tx, shop))


def test_a_gstin_that_fails_the_check_digit_is_reported(shop):  # noqa: F811
    fs = findings(shop, [line("INV-1", buyer="29AAAAA0000A1Z0")])
    assert "C-02" in codes(fs)


def test_a_b2cs_row_that_nets_negative_is_reported_unless_refdata_allows_it(shop):  # noqa: F811
    rows = [line("INV-1", taxable="100", cgst="9", sgst="9", total="118"),
            line("CN-1", kind="Credit note", original="INV-1", original_date=OCT, taxable="150", cgst="13.5",
                 sgst="13.5", total="177")]
    fs = findings(shop, rows)
    c12 = [f for f in fs if f.code == "C-12"]
    assert len(c12) == 1 and c12[0].level == "block" and c12[0].needs_ca_check


def test_checks_change_nothing_and_give_the_same_findings_twice(shop):  # noqa: F811
    monthly(shop)
    assert confirm(shop, stage(shop, month(shop))).status_code == 200
    pg, _, _ = shop
    before = [scalar(pg.owner, f"select count(*) from {t}") for t in
              ("imports.documents", "imports.document_lines", "filing.return_instances")]
    a, b = findings_in_new_month(shop), findings_in_new_month(shop)
    assert a == b and a
    assert before == [scalar(pg.owner, f"select count(*) from {t}") for t in
                      ("imports.documents", "imports.document_lines", "filing.return_instances")]
