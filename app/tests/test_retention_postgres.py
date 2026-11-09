"""The retention Lambda against the real migrations and refdata, logged in as app_retention
the way it is on AWS (L6-5, D-041). What the function may delete is covered in
tests/isolation/test_retention.py; this checks the wiring end to end.

Skipped unless PG_ADMIN_URL points at a disposable server.
"""

import os
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, make_url, text

from app import retention

PG_ADMIN_URL = os.environ.get("PG_ADMIN_URL")
REPO = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")


@pytest.fixture()
def owner_and_login(monkeypatch):
    sys.path.insert(0, str(REPO / "migrator"))
    from migrator import local

    name = f"r_{uuid.uuid4().hex[:10]}"
    admin = create_engine(PG_ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f"create database {name}"))
    url = make_url(PG_ADMIN_URL).set(database=name)
    local.main(url.set(drivername="postgresql").render_as_string(hide_password=False))
    owner = create_engine(url, isolation_level="AUTOCOMMIT")
    with owner.connect() as c:
        c.execute(text("alter role app_retention password 'test-only'"))
    login = create_engine(url.set(username="app_retention", password="test-only"))
    monkeypatch.setattr(retention.db, "engine", lambda: login)
    yield owner
    login.dispose()
    owner.dispose()
    with admin.connect() as c:
        c.execute(text(f"drop database {name} with (force)"))


def _plant_finished_job(owner):
    with owner.connect() as c:
        c.execute(
            text(
                "insert into platform.jobs (id, business_id, type, status, updated_at)"
                " values (:i, :b, 'x', 'done', now() - interval '15 days')"
            ),
            {"i": uuid.uuid4(), "b": uuid.uuid4()},
        )


def _jobs(owner):
    with owner.connect() as c:
        return c.execute(text("select count(*) from platform.jobs")).scalar_one()


def test_shipped_disabled_keeps_everything(owner_and_login):
    _plant_finished_job(owner_and_login)
    assert retention.handler({"task": "retention"}, None) == {
        "purge_operational": {"skipped": "disabled"},
        "purge_drafts": {"skipped": "disabled"},
    }
    assert _jobs(owner_and_login) == 1


def test_enabled_rule_runs_as_app_retention(owner_and_login):
    _plant_finished_job(owner_and_login)
    with owner_and_login.connect() as c:
        c.execute(text("update refdata.values set value = 'true' where key = 'retention.purge_operational.enabled'"))
    dry = retention.handler({"task": "purge_operational", "dry_run": True}, None)
    assert dry["purge_operational"]["counts"]["jobs"] == 1 and _jobs(owner_and_login) == 1
    out = retention.handler({"task": "purge_operational"}, None)
    assert out["purge_operational"]["counts"]["jobs"] == 1
    assert out["purge_operational"]["counts"]["rate_counters"] is None  # no period: kept
    assert _jobs(owner_and_login) == 0
    with owner_and_login.connect() as c:
        runs = c.execute(text("select dry_run from platform.retention_runs order by at, dry_run desc")).all()
    assert [r for (r,) in runs] == [True, False]


def test_drafts_rule_runs_as_app_retention(owner_and_login):
    biz, u, d = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with owner_and_login.connect() as c:
        c.execute(
            text(
                "insert into sales.drafts (id, business_id, kind, created_by, updated_at, updated_by)"
                " values (:d, :b, 'invoice', :u, now() - interval '181 days', :u)"
            ),
            {"d": d, "b": biz, "u": u},
        )
        c.execute(
            text("insert into sales.draft_lines (id, business_id, draft_id, line_no) values (:i, :b, :d, 1)"),
            {"i": uuid.uuid4(), "b": biz, "d": d},
        )
        c.execute(text("update refdata.values set value = 'true' where key = 'retention.purge_drafts.enabled'"))
    out = retention.handler({"task": "purge_drafts"}, None)
    assert out["purge_drafts"]["counts"] == {"drafts": 1, "draft_lines": 1}
    with owner_and_login.connect() as c:
        assert c.execute(text("select count(*) from sales.draft_lines")).scalar_one() == 0
