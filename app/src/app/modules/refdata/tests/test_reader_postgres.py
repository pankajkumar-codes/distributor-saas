"""refdata.value_on and friends on PostgreSQL, as app_rw and app_ro (LLD-0 §6.4, AC-11).

The database is built by migrator.local, which also loads the repository's refdata/
files. Skipped unless PG_ADMIN_URL points at a disposable server.
"""

import datetime as dt
import os
import re
import subprocess
import sys
import uuid
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.orm import Session

from app.modules.refdata import RefdataMissing, RefdataUnconfirmed, require_confirmed, state_name, value_on
from app.modules.refdata import reader

PG_ADMIN_URL = os.environ.get("PG_ADMIN_URL")
pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")
MIGRATOR = Path(__file__).resolve().parents[6] / "migrator"
TODAY = dt.date(2026, 10, 26)


@pytest.fixture(scope="module")
def engines():
    dbname = f"t_{uuid.uuid4().hex[:10]}"
    admin_url = make_url(PG_ADMIN_URL)
    server = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with server.connect() as c:
        c.execute(text(f"create database {dbname}"))
    dsn = admin_url.set(drivername="postgresql", database=dbname).render_as_string(hide_password=False)
    subprocess.run([sys.executable, "-m", "migrator.local", dsn], cwd=MIGRATOR, check=True, capture_output=True)
    app_rw = create_engine(admin_url.set(username="app_rw", password="local-only", database=dbname))
    admin = create_engine(admin_url.set(database=dbname), isolation_level="AUTOCOMMIT")
    yield app_rw, admin
    app_rw.dispose()
    admin.dispose()
    with server.connect() as c:
        c.execute(text(f"drop database {dbname} with (force)"))


@pytest.fixture()
def tx(engines):
    reader._reset_cache()
    with Session(engines[0]) as s:
        yield s


def add_row(admin, key, value, type_, valid_from, valid_to=None, status="provisional", kind="product"):
    """As the migrator would: a row, then a loads row so containers see the change."""
    with admin.connect() as c:
        c.execute(
            text(
                "insert into refdata.values (key, value, type, kind, valid_from, valid_to, source_url, source_title,"
                " last_checked, status, loaded_from, confirmed_by, confirmed_on) values (:k, :v, :t, :kind, :f, :to,"
                " 'https://example.org', 'test', '2026-10-26', :s, 'test', :by, :on)"
            ),
            {"k": key, "v": value, "t": type_, "kind": kind, "f": valid_from, "to": valid_to, "s": status,
             "by": None if status == "provisional" else "test", "on": None if status == "provisional" else "2026-10-26"},
        )
        c.execute(
            text(
                "insert into refdata.loads (id, git_sha, files, rows_inserted, rows_closed, rows_updated, at)"
                " values (:i, 'test', '{}', 1, 0, 0, clock_timestamp())"
            ),
            {"i": uuid.uuid4()},
        )


def test_the_loaded_rows_read_as_their_types(tx):
    assert value_on(tx, "auth.code_ttl_minutes", TODAY) == 10
    assert value_on(tx, "identity.max_owned_businesses", TODAY) == 5
    assert value_on(tx, "filing.locked_return_treatment", TODAY) == "refuse"
    pattern = value_on(tx, "invoice.number.charset", TODAY)
    assert isinstance(pattern, re.Pattern) and pattern.fullmatch("INV/26-27/0001")
    assert not pattern.fullmatch("INV 1")


def test_no_row_on_the_date_raises_never_a_default(tx):
    with pytest.raises(RefdataMissing) as e:
        value_on(tx, "qrmp.option_window.start", TODAY)
    assert (e.value.key, e.value.found) == ("qrmp.option_window.start", 0)
    with pytest.raises(RefdataMissing):
        value_on(tx, "auth.code_ttl_minutes", dt.date(2026, 10, 23))  # before valid_from


def test_a_new_load_is_seen_by_the_next_call_and_dates_pick_the_row(engines, tx):
    _, admin = engines
    add_row(admin, "test.rate", "0.05", "decimal", "2026-01-01", "2026-11-01")
    assert value_on(tx, "test.rate", TODAY) == Decimal("0.05")
    add_row(admin, "test.rate", "0.06", "decimal", "2026-11-01")
    assert value_on(tx, "test.rate", dt.date(2026, 10, 31)) == Decimal("0.05")
    assert value_on(tx, "test.rate", dt.date(2026, 11, 1)) == Decimal("0.06")
    add_row(admin, "test.flag", "true", "boolean", "2026-01-01")
    assert value_on(tx, "test.flag", TODAY) is True


def test_require_confirmed_wants_the_right_party_for_the_kind(engines, tx):
    _, admin = engines
    with pytest.raises(RefdataUnconfirmed):
        require_confirmed(tx, "auth.code_ttl_minutes", TODAY)  # provisional
    add_row(admin, "test.product_ok", "1", "integer", "2026-01-01", status="po_confirmed")
    add_row(admin, "test.tax_ok", "1", "integer", "2026-01-01", status="ca_confirmed", kind="tax")
    require_confirmed(tx, "test.product_ok", TODAY)
    require_confirmed(tx, "test.tax_ok", TODAY)


def test_state_name(tx):
    assert state_name(tx, "19", TODAY) == "West Bengal"
    assert state_name(tx, "96", TODAY) == "Other Country"
    assert state_name(tx, "25", TODAY) is None  # merged into 26; not for new entries
    assert state_name(tx, "XX", TODAY) is None


def test_on_must_be_a_date_not_a_datetime(tx):
    with pytest.raises(TypeError):
        value_on(tx, "auth.code_ttl_minutes", dt.datetime(2026, 10, 26, 12, 0))


def test_app_ro_reads_refdata_too(engines):
    reader._reset_cache()
    with Session(engines[0]) as s, s.begin():
        s.execute(text("set local role app_ro"))
        assert value_on(s, "auth.code_max_tries", TODAY) == 5
