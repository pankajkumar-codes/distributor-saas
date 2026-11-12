"""Return instances and assignment on PostgreSQL as app_rw (LLD-5 §2.1, §4, §8; LLD-4 §11).

Due dates are the GST expert's worked examples (team/gst/refdata-lld4.md §3 "Tests"), read
back through the refdata rows in refdata/values/returns.yaml. Skipped unless PG_ADMIN_URL
is set.
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.modules.filing.periods import (
    DocumentRef,
    PeriodLocked,
    assert_period_open,
    ensure_instances,
    target_return_instance,
)
from platform_common.errors import Conflict

from .conftest import PG_ADMIN_URL, as_user, ctx, new_business, scalar, user_id

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")

D = Decimal
GSTIN = "19AAPFU0939F1ZS"  # the business new_business creates: state 19, synthetic
TODAY = date(2026, 11, 9)


@pytest.fixture()
def biz(pg):
    b = new_business(pg, "alice")
    return pg, b, user_id(pg.owner, "alice")


def choose(pg, b, frequency, effective_from="2026-10-01", sub="alice"):
    r = pg.client.post(
        f"/api/v1/b/{b}/filing-profile/frequency",
        json={"frequency": frequency, "effective_from": effective_from},
        headers={**as_user(sub), "Idempotency-Key": uuid.uuid4().hex},
    )
    assert r.status_code in (200, 201), r.text


def tx_for(pg, b, alice, fn, *, user=None):
    with pg.app_rw.begin() as c:
        ctx(c, user or alice, b)
        return fn(c)


def lock(pg, b, instance_id, status="filed_locked", *, event="filed"):
    """Mark an instance filed as the database owner would after the (later) mark-filed
    slice: the event row first, in the same transaction, so the status guard allows it."""
    # The owner engine autocommits; the guard needs both statements in one transaction.
    with pg.owner.execution_options(isolation_level="READ COMMITTED").begin() as c:
        c.execute(text("select set_config('app.tenant_id', :b, true)"), {"b": str(b)})
        c.execute(
            text(
                "insert into filing.instance_events (id, business_id, instance_id, kind, filed_on)"
                " values (:i, :b, :n, :k, :d)"
            ),
            {"i": uuid.uuid4(), "b": b, "n": instance_id, "k": event, "d": TODAY},
        )
        c.execute(
            text("update filing.return_instances set status = :s, status_changed_at = now() where id = :n"),
            {"s": status, "n": instance_id},
        )


def rows(instances):
    return [(i.form, i.period, i.period_start, i.period_end, i.due_date) for i in instances]


# -- Calendar: the expert's worked examples ------------------------------------------------


def test_qrmp_quarter_instances_and_due_dates(biz):  # refdata-lld4.md §3 tests: Oct-Dec 2026, state 19
    pg, b, alice = biz
    choose(pg, b, "quarterly")
    got = tx_for(pg, b, alice, lambda tx: ensure_instances(tx, GSTIN, date(2026, 11, 20)))
    assert rows(got) == [  # by period start, then form order IFF, PMT-06, GSTR-1, GSTR-3B
        ("IFF", "2026-10", date(2026, 10, 1), date(2026, 10, 31), date(2026, 11, 13)),
        ("PMT06", "2026-10", date(2026, 10, 1), date(2026, 10, 31), date(2026, 11, 25)),
        ("GSTR1", "2026-12", date(2026, 10, 1), date(2026, 12, 31), date(2027, 1, 13)),
        ("GSTR3B", "2026-12", date(2026, 10, 1), date(2026, 12, 31), date(2027, 1, 24)),  # state 19: the 24th group
        ("IFF", "2026-11", date(2026, 11, 1), date(2026, 11, 30), date(2026, 12, 13)),
        ("PMT06", "2026-11", date(2026, 11, 1), date(2026, 11, 30), date(2026, 12, 25)),
    ]


def test_monthly_filer_instances_and_due_dates(biz):  # October 2026: GSTR-1 on 11 Nov, 3B on 20 Nov
    pg, b, alice = biz
    choose(pg, b, "monthly")
    got = tx_for(pg, b, alice, lambda tx: ensure_instances(tx, GSTIN, date(2026, 10, 5)))
    assert [r for r in rows(got) if r[2] == date(2026, 10, 1)] == [
        ("GSTR1", "2026-10", date(2026, 10, 1), date(2026, 10, 31), date(2026, 11, 11)),
        ("GSTR3B", "2026-10", date(2026, 10, 1), date(2026, 10, 31), date(2026, 11, 20)),
    ]
    assert len(got) == 6  # three months x GSTR-1 and GSTR-3B


@pytest.mark.parametrize(
    "gstin, due",
    [
        ("27AAPFU0939F1ZV", date(2027, 1, 22)),
        ("07AAPFU0939F1ZZ", date(2027, 1, 24)),
    ],  # synthetic; the check digit isn't read
)
def test_quarterly_3b_day_follows_the_gstin_state_group(biz, gstin, due):
    pg, b, alice = biz
    choose(pg, b, "quarterly")
    # filing_frequency_on is per GSTIN; seed the row for the other GSTIN as the owner would.
    with pg.owner.begin() as c:
        c.execute(
            text(
                "insert into business.filing_frequency_history (id, business_id, gstin, frequency, effective_from,"
                " chosen_at, warnings, chosen_by) values (:i, :b, :g, 'quarterly', '2026-10-01', now(), '{}', :u)"
            ),
            {"i": uuid.uuid4(), "b": b, "g": gstin, "u": alice},
        )
    got = tx_for(pg, b, alice, lambda tx: ensure_instances(tx, gstin, date(2026, 11, 20)))
    assert [i.due_date for i in got if i.form == "GSTR3B"] == [due]


def test_a_state_in_neither_3b_group_has_no_due_date_never_a_guess(biz):
    pg, b, alice = biz
    choose(pg, b, "quarterly")
    with pg.owner.begin() as c:
        c.execute(
            text(
                "insert into business.filing_frequency_history (id, business_id, gstin, frequency, effective_from,"
                " chosen_at, warnings, chosen_by) values (:i, :b, '97AAPFU0939F1Z1', 'quarterly', '2026-10-01', now(), '{}', :u)"
            ),
            {"i": uuid.uuid4(), "b": b, "u": alice},
        )
    got = tx_for(pg, b, alice, lambda tx: ensure_instances(tx, "97AAPFU0939F1Z1", date(2026, 11, 20)))
    assert [i.due_date for i in got if i.form == "GSTR3B"] == [None]
    assert [i.due_date for i in got if i.form == "GSTR1"] == [date(2027, 1, 13)]


def test_ensure_instances_is_idempotent(biz):
    pg, b, alice = biz
    choose(pg, b, "quarterly")
    first = tx_for(pg, b, alice, lambda tx: ensure_instances(tx, GSTIN, date(2026, 10, 1)))
    again = tx_for(pg, b, alice, lambda tx: ensure_instances(tx, GSTIN, date(2026, 12, 31)))
    assert [i.id for i in first] == [i.id for i in again]
    assert scalar(pg.owner, "select count(*) from filing.return_instances") == 6


def test_no_frequency_set_is_a_409_with_the_checklist_message(biz):
    pg, b, alice = biz
    with pytest.raises(Conflict) as e:
        tx_for(pg, b, alice, lambda tx: ensure_instances(tx, GSTIN, date(2026, 11, 20)))
    assert (e.value.status, e.value.code) == (409, "filing_frequency_not_set")


# -- Assignment (LLD-5 §4) -----------------------------------------------------------------


def assign(pg, b, alice, kind, on, cls, *, taxable=None, original=None, today=TODAY):
    return tx_for(
        pg, b, alice,
        lambda tx: target_return_instance(tx, GSTIN, kind, on, cls, original, taxable_value=taxable, today=today),
    )  # fmt: skip


@pytest.mark.parametrize(
    "kind, on, cls, form, period",
    [
        ("invoice", date(2026, 10, 5), "B2B", "IFF", "2026-10"),  # months 1 and 2: B2B to the IFF
        ("invoice", date(2026, 11, 10), "B2B", "IFF", "2026-11"),
        ("invoice", date(2026, 12, 5), "B2B", "GSTR1", "2026-12"),  # month 3: the quarter
        ("invoice", date(2026, 10, 5), "B2CS", "GSTR1", "2026-12"),  # B2C never in an IFF
        ("invoice", date(2026, 10, 5), "B2CL", "GSTR1", "2026-12"),
        ("credit_note", date(2026, 10, 20), "CDNR", "IFF", "2026-10"),  # registered notes follow B2B
        ("credit_note", date(2026, 10, 20), "CDNUR", "GSTR1", "2026-12"),
        ("credit_note", date(2026, 10, 20), "B2CS", "GSTR1", "2026-12"),
    ],
)
def test_qrmp_routing_table(biz, kind, on, cls, form, period):
    pg, b, alice = biz
    choose(pg, b, "quarterly")
    got = assign(pg, b, alice, kind, on, cls, taxable=D("100.00"), today=date(2026, 11, 9) if on.month == 10 else on)
    assert (got.form, got.period) == (form, period)


def test_monthly_filer_goes_to_the_month_s_gstr1(biz):
    pg, b, alice = biz
    choose(pg, b, "monthly")
    got = assign(pg, b, alice, "invoice", date(2026, 10, 20), "B2B", taxable=D("1.00"))
    assert (got.form, got.period, got.due_date) == ("GSTR1", "2026-10", date(2026, 11, 11))


def test_an_invoice_after_the_iff_due_date_goes_to_the_quarter(biz):  # Part B Q2: dated 28-10, finalized 15-11
    pg, b, alice = biz
    choose(pg, b, "quarterly")
    got = assign(pg, b, alice, "invoice", date(2026, 10, 28), "B2B", taxable=D("10000.00"), today=date(2026, 11, 15))
    assert (got.form, got.period) == ("GSTR1", "2026-12")


def test_a_locked_iff_sends_a_later_invoice_to_the_quarter_by_construction(biz):  # Part B, HLD §5.4
    pg, b, alice = biz
    choose(pg, b, "quarterly")
    q1 = assign(pg, b, alice, "invoice", date(2026, 10, 5), "B2B", taxable=D("50000.00"), today=date(2026, 10, 5))
    assert q1.form == "IFF"
    lock(pg, b, q1.id)
    q2 = assign(pg, b, alice, "invoice", date(2026, 10, 28), "B2B", taxable=D("10000.00"), today=date(2026, 11, 12))
    assert (q2.form, q2.period) == ("GSTR1", "2026-12")  # not the locked IFF, and not refused


def test_the_iff_cap_moves_an_invoice_to_the_quarter_and_notes_dont_count(biz):  # L5-3
    pg, b, alice = biz
    choose(pg, b, "quarterly")
    on = date(2026, 10, 5)
    a = assign(pg, b, alice, "invoice", on, "B2B", taxable=D("4000000.00"), today=on)
    b2 = assign(pg, b, alice, "invoice", on, "B2B", taxable=D("1000000.00"), today=on)  # exactly the cap
    over = assign(pg, b, alice, "invoice", on, "B2B", taxable=D("0.01"), today=on)
    assert (a.form, b2.form, over.form) == ("IFF", "IFF", "GSTR1")
    iff_total = "select iff_b2b_taxable from filing.return_instances where form = 'IFF' and return_period = '2026-10'"
    assert scalar(pg.owner, iff_total) == D("5000000.00")
    note = assign(pg, b, alice, "credit_note", on, "CDNR", today=on)  # no taxable_value needed
    assert note.form == "IFF"
    assert scalar(pg.owner, iff_total) == D("5000000.00")


def test_a_qrmp_b2b_invoice_needs_its_taxable_value(biz):
    pg, b, alice = biz
    choose(pg, b, "quarterly")
    with pytest.raises(ValueError, match="taxable_value"):
        assign(pg, b, alice, "invoice", date(2026, 10, 5), "B2B")


def test_the_running_total_rolls_back_with_the_transaction(biz):
    pg, b, alice = biz
    choose(pg, b, "quarterly")
    with pytest.raises(RuntimeError):
        with pg.app_rw.begin() as c:
            ctx(c, alice, b)
            target_return_instance(
                c, GSTIN, "invoice", date(2026, 10, 5), "B2B", taxable_value=D("123.00"), today=TODAY
            )
            raise RuntimeError("finalize failed after assignment")
    assert scalar(pg.owner, "select coalesce(sum(iff_b2b_taxable), 0) from filing.return_instances") == D("0")


# -- Locked returns (LLD-5 §4 steps 4-5, L5-4) ----------------------------------------------


def test_an_invoice_in_a_locked_return_is_refused_with_period_locked(biz):  # D-034, CA-1 (a)
    pg, b, alice = biz
    choose(pg, b, "monthly")
    inst = assign(pg, b, alice, "invoice", date(2026, 10, 20), "B2B", taxable=D("1.00"))
    lock(pg, b, inst.id)
    with pytest.raises(PeriodLocked) as e:
        assign(pg, b, alice, "invoice", date(2026, 10, 21), "B2B", taxable=D("1.00"))
    assert (e.value.status, e.value.code) == (409, "period_locked")
    assert "GSTR-1 Oct 2026" in e.value.message
    with pytest.raises(PeriodLocked):
        tx_for(pg, b, alice, lambda tx: assert_period_open(tx, inst.id))


def test_an_unlocked_return_still_refuses_new_documents(biz):  # filing.locked_return_treatment = refuse
    pg, b, alice = biz
    choose(pg, b, "monthly")
    inst = assign(pg, b, alice, "invoice", date(2026, 10, 20), "B2B", taxable=D("1.00"))
    lock(pg, b, inst.id)
    lock(pg, b, inst.id, "unlocked", event="unlocked")
    with pytest.raises(PeriodLocked):
        assign(pg, b, alice, "invoice", date(2026, 10, 21), "B2B", taxable=D("1.00"))


def test_a_backdated_credit_note_rolls_forward_to_the_open_return_for_today(biz):  # L5-4, CA-1 (c)
    pg, b, alice = biz
    choose(pg, b, "monthly", "2026-10-01")
    inst = assign(pg, b, alice, "invoice", date(2026, 10, 20), "B2B", taxable=D("1.00"), today=date(2026, 10, 25))
    lock(pg, b, inst.id)
    note = assign(
        pg, b, alice, "credit_note", date(2026, 10, 25), "CDNR",
        original=DocumentRef(uuid.uuid4(), "INV/1", date(2026, 10, 20)), today=date(2026, 11, 3),
    )  # fmt: skip
    assert (note.form, note.period, note.rolled_forward_from) == ("GSTR1", "2026-11", inst.id)


def test_a_credit_note_is_refused_when_today_s_return_is_locked_too(biz):
    pg, b, alice = biz
    choose(pg, b, "monthly", "2026-10-01")
    for on in (date(2026, 10, 20), date(2026, 11, 3)):
        lock(pg, b, assign(pg, b, alice, "invoice", on, "B2B", taxable=D("1.00"), today=on).id)
    with pytest.raises(PeriodLocked):
        assign(pg, b, alice, "credit_note", date(2026, 10, 25), "CDNR", today=date(2026, 11, 3))


# -- Database guards, isolation ------------------------------------------------------------


def test_status_cannot_change_without_its_event_row(biz):  # [RM45-8]
    pg, b, alice = biz
    choose(pg, b, "monthly")
    inst = assign(pg, b, alice, "invoice", date(2026, 10, 20), "B2B", taxable=D("1.00"))
    with pytest.raises(DBAPIError, match="needs a filed event"):
        with pg.app_rw.begin() as c:
            ctx(c, alice, b)
            c.execute(text("update filing.return_instances set status = 'filed_locked' where id = :i"), {"i": inst.id})
    with pytest.raises(DBAPIError, match="cannot go from open to unlocked"):
        with pg.app_rw.begin() as c:
            ctx(c, alice, b)
            c.execute(text("update filing.return_instances set status = 'unlocked' where id = :i"), {"i": inst.id})
    with pytest.raises(DBAPIError, match="cannot go down"):
        with pg.app_rw.begin() as c:
            ctx(c, alice, b)
            c.execute(text("update filing.return_instances set iff_b2b_taxable = -1 where id = :i"), {"i": inst.id})


def test_app_rw_cannot_delete_instances_or_events(biz):
    pg, b, alice = biz
    choose(pg, b, "monthly")
    inst = assign(pg, b, alice, "invoice", date(2026, 10, 20), "B2B", taxable=D("1.00"))
    for sql in ("delete from filing.return_instances", "delete from filing.instance_events",
                "update filing.return_instances set gstin = '19AAPFU0939F1Z0'"):  # fmt: skip
        with pytest.raises(DBAPIError):
            with pg.app_rw.begin() as c:
                ctx(c, alice, b)
                c.execute(text(sql))
    assert inst.id


def test_another_business_never_sees_or_locks_these_instances(biz):  # tenant isolation
    pg, b, alice = biz
    choose(pg, b, "monthly")
    inst = assign(pg, b, alice, "invoice", date(2026, 10, 20), "B2B", taxable=D("1.00"))
    other = new_business(pg, "bob")
    bob = user_id(pg.owner, "bob")
    assert (
        tx_for(pg, other, bob, lambda tx: tx.execute(text("select count(*) from filing.return_instances")).scalar())
        == 0
    )
    with pytest.raises(LookupError):
        tx_for(pg, other, bob, lambda tx: assert_period_open(tx, inst.id))
    with pytest.raises(DBAPIError):  # a forged business_id fails the RLS check
        with pg.app_rw.begin() as c:
            ctx(c, bob, other)
            c.execute(
                text(
                    "insert into filing.return_instances (id, business_id, gstin, form, frequency, filer_frequency,"
                    " period_start, period_end, return_period, due_date, due_date_ref)"
                    " values (:i, :b, :g, 'GSTR1', 'monthly', 'monthly', '2026-10-01', '2026-10-31', '2026-10',"
                    " '2026-11-11', 'x')"
                ),
                {"i": uuid.uuid4(), "b": b, "g": GSTIN},
            )
