"""Import runs on SQLite: idempotent staging and cross-file comparison."""

import uuid

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.modules.imports import staging
from app.modules.imports.models import Base, ImportRow, ImportRun, RunStatus, StagedRowStatus
from app.modules.imports.parsing import FieldKind, FieldSpec, MappingProfile, read_table

PROFILE = MappingProfile(
    marketplace="flipkart",
    report_type="orders",
    version="test-1",
    fields=(
        FieldSpec("order_item_id", ("Order Item ID",)),
        FieldSpec("status", ("Status",)),
        FieldSpec("amount", ("Amount",), FieldKind.decimal),
    ),
    dedup_key=("order_item_id",),
)
TENANT_A = uuid.uuid4()
TENANT_B = uuid.uuid4()


@pytest.fixture()
def session():
    eng = create_engine("sqlite+pysqlite:///:memory:").execution_options(schema_translate_map={"imports": None})
    Base.metadata.create_all(eng)
    with Session(eng) as s:
        yield s


def table(body: str, name: str = "orders.csv"):
    return read_table(("Order Item ID,Status,Amount\n" + body).encode(), name)


def stage(session, body, tenant=TENANT_A, name="orders.csv", profile=PROFILE):
    run, created = staging.stage(session, tenant_id=tenant, user_sub="alice", table=table(body, name), profile=profile)
    session.commit()
    return run, created


def row_statuses(session, run):
    rows = session.scalars(select(ImportRow).where(ImportRow.run_id == run.id).order_by(ImportRow.row_number))
    return [r.status for r in rows]


def test_stage_stores_raw_normalized_and_summary(session):
    run, created = stage(session, "OI-1,shipped,\"1,250.50\"\nOI-2,shipped,abc\nOI-1,shipped,1250.5\n")
    assert created and run.status == RunStatus.staged
    assert run.summary["new"] == 1 and run.summary["invalid"] == 1 and run.summary["duplicate"] == 1
    first = session.scalar(select(ImportRow).where(ImportRow.run_id == run.id, ImportRow.row_number == 2))
    assert first.raw == {"Order Item ID": "OI-1", "Status": "shipped", "Amount": "1,250.50"}
    assert first.normalized == {"order_item_id": "OI-1", "status": "shipped", "amount": "1250.50"}
    dup = session.scalar(select(ImportRow).where(ImportRow.run_id == run.id, ImportRow.row_number == 4))
    assert dup.errors[0]["code"] == "duplicate" and dup.errors[0]["related_rows"] == [2]
    assert run.profile_verified is False and run.profile_id == "flipkart/orders@test-1"
    assert first.dedup_values == ["OI-1"]


def test_same_file_twice_returns_the_same_run(session):
    run, _ = stage(session, "OI-1,shipped,10\n")
    again, created = stage(session, "OI-1,shipped,10\n", name="renamed copy.csv")
    assert not created and again.id == run.id
    assert session.scalar(select(func.count()).select_from(ImportRun)) == 1
    assert session.scalar(select(func.count()).select_from(ImportRow)) == 1


def test_same_file_for_another_tenant_is_independent(session):
    a, _ = stage(session, "OI-1,shipped,10\n", tenant=TENANT_A)
    b, created = stage(session, "OI-1,shipped,10\n", tenant=TENANT_B)
    assert created and a.id != b.id


def test_later_file_compares_against_confirmed_runs_only(session):
    first, _ = stage(session, "OI-1,shipped,10\nOI-2,shipped,20\n")
    # Not confirmed yet: everything in the next file still counts as new.
    second, _ = stage(session, "OI-1,shipped,10\nOI-3,shipped,30\n")
    assert row_statuses(session, second) == [StagedRowStatus.new, StagedRowStatus.new]

    staging.confirm(session, tenant_id=TENANT_A, run_id=first.id, user_sub="alice")
    session.commit()
    third, _ = stage(session, "OI-1,shipped,10.00\nOI-2,delivered,20\nOI-4,shipped,40\n")
    assert row_statuses(session, third) == [
        StagedRowStatus.already_imported,  # 10 == 10.00
        StagedRowStatus.changed,  # status moved on
        StagedRowStatus.new,
    ]


def test_changed_row_compares_against_latest_confirmation(session):
    first, _ = stage(session, "OI-1,shipped,10\n")
    staging.confirm(session, tenant_id=TENANT_A, run_id=first.id, user_sub="alice")
    second, _ = stage(session, "OI-1,delivered,10\n")
    staging.confirm(session, tenant_id=TENANT_A, run_id=second.id, user_sub="alice")
    session.commit()
    third, _ = stage(session, "OI-1,delivered,10\n\n")  # different bytes, same content
    assert row_statuses(session, third) == [StagedRowStatus.already_imported]


def test_other_tenants_confirmed_rows_are_never_consulted(session):
    other, _ = stage(session, "OI-1,shipped,10\n", tenant=TENANT_B)
    staging.confirm(session, tenant_id=TENANT_B, run_id=other.id, user_sub="bob")
    session.commit()
    mine, _ = stage(session, "OI-1,shipped,10\n\n", tenant=TENANT_A)
    assert row_statuses(session, mine) == [StagedRowStatus.new]


def test_other_report_types_are_never_consulted(session):
    returns = MappingProfile(
        marketplace="flipkart", report_type="returns", version="t", fields=PROFILE.fields, dedup_key=PROFILE.dedup_key
    )
    run, _ = stage(session, "OI-1,returned,10\n", profile=returns)
    staging.confirm(session, tenant_id=TENANT_A, run_id=run.id, user_sub="alice")
    session.commit()
    orders, _ = stage(session, "OI-1,returned,10\n")
    assert row_statuses(session, orders) == [StagedRowStatus.new]


def test_confirm_is_idempotent_and_tenant_checked(session):
    run, _ = stage(session, "OI-1,shipped,10\n")
    with pytest.raises(LookupError):
        staging.confirm(session, tenant_id=TENANT_B, run_id=run.id, user_sub="mallory")
    once = staging.confirm(session, tenant_id=TENANT_A, run_id=run.id, user_sub="alice")
    at = once.confirmed_at
    twice = staging.confirm(session, tenant_id=TENANT_A, run_id=run.id, user_sub="someone-else")
    assert twice.confirmed_at == at and twice.confirmed_by == "alice"
    with pytest.raises(staging.RunStateError):
        staging.discard(session, tenant_id=TENANT_A, run_id=run.id)


def test_discarded_file_can_be_staged_again(session):
    run, _ = stage(session, "OI-1,shipped,10\n")
    staging.discard(session, tenant_id=TENANT_A, run_id=run.id)
    session.commit()
    again, created = stage(session, "OI-1,shipped,10\n")
    assert created and again.id != run.id
    with pytest.raises(staging.RunStateError):
        staging.confirm(session, tenant_id=TENANT_A, run_id=run.id, user_sub="alice")
