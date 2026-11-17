"""Insert-only snapshots (R1-M8 S2): rows, members, versions, retry, tenant isolation."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.modules.filing import periods, snapshots
from app.modules.filing.build import ReturnBuild
from app.modules.filing.gstr1 import Amounts, build_sections

from .conftest import PG_ADMIN_URL, as_user, ctx, new_business, scalar, user_id
from .test_gstr1_sections import CN, INV, KA, SOAP, TEA, WB, A, I3, line
from .test_periods_postgres import choose

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")
D = Decimal


@pytest.fixture()
def ret(pg):
    from app import api as app_api
    from platform_common.clock import IST, FrozenClock, get_clock

    app_api.app.dependency_overrides[get_clock] = lambda: FrozenClock(datetime(2026, 11, 15, 12, 0, tzinfo=IST))
    b = new_business(pg, "alice")
    choose(pg, b, "monthly")
    rows = pg.client.get(f"/api/v1/b/{b}/returns", params={"fy": "2026-27"}, headers=as_user("alice")).json()["returns"]
    inst = uuid.UUID(next(x["instance_id"] for x in rows if x["form"] == "GSTR1" and x["period"] == "2026-10"))
    return pg, b, inst


def lines():
    return [
        line("INV-1", 5, INV, "B2B", WB, SOAP, "10", "1000.00", cgst="90.00", sgst="90.00", value="1180.00", buyer=A),
        line("INV-2", 6, INV, "B2CS", KA, TEA, "2.5", "200.00", igst="10.00", value="210.00"),
        line("CN-1", 7, CN, "CDNR", WB, SOAP, "1", "100.00", cgst="9.00", sgst="9.00", value="118.00", buyer=A,
             original=("INV-1", I3)),
    ]  # fmt: skip


def build_of(instance, ls, fingerprint="a" * 64):
    s = build_sections(ls, kind=instance.form)
    return ReturnBuild(
        instance=instance, sections=s, liability=Amounts(), hsn_total=Amounts(), gap=Amounts(),
        members=(), line_items=s.line_items, fingerprint=fingerprint, refdata_as_of={"k": "2026-01-01"},
        ca_flags=(), debit_notes=0, draft=True, lines=tuple(ls),
    )  # fmt: skip


def write(pg, b, inst, ls=None, *, as_sub="alice", **kw):
    """One snapshot written in its own transaction as the business's app role."""
    uid = user_id(pg.owner, as_sub)
    with pg.app_rw.begin() as c:
        ctx(c, uid, b)
        instance = periods.get_instance(c, inst)
        uow = SimpleNamespace(tx=c, principal=SimpleNamespace(business_id=b, user_id=uid))
        return snapshots.write_snapshot(uow, instance, build_of(instance, ls or lines()), **kw)


def test_a_snapshot_keeps_every_row_the_documents_and_the_totals_exactly(ret):
    pg, b, inst = ret
    s = write(pg, b, inst, purpose="export", template_version="2.2")
    assert (s.version, s.purpose, s.created) == (1, "export", True)
    with pg.app_rw.begin() as c:
        ctx(c, user_id(pg.owner, "alice"), b)
        rows = snapshots.read_rows(c, s.id)
        members = snapshots.read_members(c, s.id)
    ls = lines()
    assert [(r["section"], r["row_no"]) for r in rows][:3] == [("b2b", 1), ("b2cs", 2), ("cdnr", 3)]
    b2b = rows[0]
    assert (b2b["doc_number"], b2b["doc_date"], b2b["counterparty_gstin"], b2b["rate"]) == (
        "INV-1",
        date(2026, 10, 5),
        A,
        D("18.00"),
    )
    assert (b2b["taxable_value"], b2b["cgst"], b2b["sgst"], b2b["invoice_value"]) == (
        D("1000.00"),
        D("90.00"),
        D("90.00"),
        D("1180.00"),
    )
    cdnr = next(r for r in rows if r["section"] == "cdnr")
    assert cdnr["note_type"] == "C" and cdnr["taxable_value"] == D("100.00")
    hsn = [r for r in rows if r["section"] == "hsn_b2c"]
    assert hsn and hsn[0]["quantity"] == D("2.500")  # three decimals kept
    assert members == {(ln.source_kind, ln.source_id) for ln in ls}
    snap = pg.owner.connect().execute(
        text("select builder_version, template_version, refdata_as_of, totals, purpose, fingerprint"
             " from filing.return_snapshots where id = :i"), {"i": s.id}).one()  # fmt: skip
    assert snap.builder_version == snapshots.BUILDER_VERSION and snap.template_version == "2.2"
    assert snap.refdata_as_of == {"k": "2026-01-01"} and snap.fingerprint == "a" * 64
    assert snap.totals["line_items"] == build_sections(ls, kind="GSTR1").line_items


def test_versions_count_up_per_instance_and_a_retry_returns_the_same_snapshot(ret):
    pg, b, inst = ret
    first = write(pg, b, inst, purpose="export")
    sid = uuid.uuid4()
    second = write(pg, b, inst, purpose="export", snapshot_id=sid)
    again = write(pg, b, inst, purpose="export", snapshot_id=sid)
    assert (first.version, second.version, again.version) == (1, 2, 2)
    assert again.id == second.id and again.created is False
    assert scalar(pg.owner, "select count(*) from filing.return_snapshots") == 2
    assert scalar(pg.owner, "select count(*) from filing.snapshot_lines where snapshot_id = :s", s=sid) == len(
        snapshots.rows_of(build_sections(lines(), kind="GSTR1"))
    )
    with pg.app_rw.begin() as c:
        ctx(c, user_id(pg.owner, "alice"), b)
        assert snapshots.latest(c, inst, "export").id == sid and snapshots.latest(c, inst, "lock") is None


def test_two_writers_on_one_instance_get_distinct_versions(ret):
    from concurrent.futures import ThreadPoolExecutor

    pg, b, inst = ret
    with ThreadPoolExecutor(4) as ex:
        got = list(ex.map(lambda i: write(pg, b, inst, purpose="export").version, range(4)))
    assert sorted(got) == [1, 2, 3, 4]


def test_a_lock_after_an_export_is_the_next_version_with_its_difference_recorded(ret):
    pg, b, inst = ret
    write(pg, b, inst, purpose="export")
    lock = write(
        pg, b, inst, purpose="lock", changed_since_export=True, accept_reason="portal differs",
        difference={"added": ["INV-9"], "removed": []},
    )  # fmt: skip
    assert lock.version == 2
    row = pg.owner.connect().execute(
        text("select changed_since_export, accept_reason, difference from filing.return_snapshots where id = :i"),
        {"i": lock.id},
    ).one()  # fmt: skip
    assert row == (True, "portal differs", {"added": ["INV-9"], "removed": []})


def test_the_table_refuses_a_difference_without_a_reason_or_on_an_export(ret):
    pg, b, inst = ret
    with pytest.raises(DBAPIError):
        write(pg, b, inst, purpose="lock", changed_since_export=True)
    with pytest.raises(DBAPIError):
        write(pg, b, inst, purpose="export", changed_since_export=True, accept_reason="x", difference={})
    assert scalar(pg.owner, "select count(*) from filing.return_snapshots") == 0


def test_a_snapshot_cannot_be_changed_or_removed_by_anyone(ret):
    pg, b, inst = ret
    s = write(pg, b, inst, purpose="export")
    for sql in (
        "update filing.return_snapshots set fingerprint = repeat('b', 64)",
        "delete from filing.return_snapshots",
        "update filing.snapshot_lines set taxable_value = 1",
        "delete from filing.snapshot_lines",
        "update filing.snapshot_members set via_instance = gen_random_uuid()",
        "delete from filing.snapshot_members",
        "truncate filing.snapshot_lines",
    ):
        with pytest.raises(DBAPIError, match="insert-only"), pg.owner.connect() as c:
            c.execute(text(sql))
    assert scalar(pg.owner, "select count(*) from filing.snapshot_lines where snapshot_id = :s", s=s.id) > 0


def test_a_snapshot_is_seen_only_by_its_own_business(ret):
    pg, b, inst = ret
    s = write(pg, b, inst, purpose="export")
    other = new_business(pg, "mallory")
    with pg.app_rw.begin() as c:
        ctx(c, user_id(pg.owner, "mallory"), other)
        assert snapshots.latest(c, inst, "export") is None
        assert snapshots.read_rows(c, s.id) == [] and snapshots.read_members(c, s.id) == set()
        with pytest.raises(DBAPIError, match="row-level security"):
            c.execute(
                text(
                    "insert into filing.return_snapshots (id, business_id, instance_id, version, purpose, fingerprint,"
                    " builder_version, refdata_as_of) values (gen_random_uuid(), :b, :i, 9, 'export', repeat('a', 64),"
                    " 'x', '{}')"
                ),
                {"b": b, "i": inst},
            )


def test_the_table_refuses_another_businesss_instance_even_for_the_owner_role(ret):
    pg, b, inst = ret
    other = new_business(pg, "mallory")
    with pytest.raises(DBAPIError, match="foreign key"), pg.owner.connect() as c:
        c.execute(
            text(
                "insert into filing.return_snapshots (id, business_id, instance_id, version, purpose, fingerprint,"
                " builder_version, refdata_as_of) values (gen_random_uuid(), :b, :i, 1, 'export', repeat('a', 64),"
                " 'x', '{}')"
            ),
            {"b": other, "i": inst},
        )


def test_an_empty_return_still_writes_a_snapshot_and_a_build_of_another_return_is_refused(ret):
    pg, b, inst = ret
    assert write(pg, b, inst, ls=[], purpose="lock").version == 1
    uid = user_id(pg.owner, "alice")
    with pg.app_rw.begin() as c:
        ctx(c, uid, b)
        instance = periods.get_instance(c, inst)
        other = SimpleNamespace(**{**instance.__dict__, "id": uuid.uuid4()})
        uow = SimpleNamespace(tx=c, principal=SimpleNamespace(business_id=b, user_id=uid))
        with pytest.raises(ValueError):
            snapshots.write_snapshot(uow, instance, build_of(other, []), purpose="export")
        with pytest.raises(ValueError):
            snapshots.write_snapshot(uow, instance, build_of(instance, []), purpose="draft")


def test_the_rows_of_a_build_are_numbered_in_section_order():
    rows = snapshots.rows_of(build_sections(lines(), kind="GSTR1"))
    assert [r["row_no"] for r in rows] == list(range(1, len(rows) + 1))
    order = [r["section"] for r in rows]
    assert order == sorted(order, key=["b2b", "b2cl", "b2cs", "cdnr", "cdnur", "hsn_b2b", "hsn_b2c"].index)
