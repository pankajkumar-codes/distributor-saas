"""The refdata loader (LLD-0 §6.3, AC-11). File checks run anywhere; loads need
PG_DSN=postgresql://postgres@localhost:5432/postgres"""

import hashlib
import json
import os
import shutil
import uuid
from pathlib import Path

import psycopg
import pytest

from migrator.handler import migrate
from migrator.local import collect
from migrator.refdata import RefdataInvalid, load, main, read_files

REPO_REFDATA = Path(__file__).resolve().parents[2] / "refdata"
DSN = os.environ.get("PG_DSN")
needs_pg = pytest.mark.skipif(not DSN, reason="PG_DSN not set")

CONFIRMED = '  confirmed_by: "GST expert, RS-9"\n  confirmed_on: 2026-10-20\n'
ENTRY = """\
- key: test.limit
  value: "{value}"
  type: integer
  kind: product
  valid_from: {valid_from}
  source_url: https://example.org/source
  source_title: "Test source"
  last_checked: 2026-10-26
  status: provisional
"""


def tree(tmp_path, *entries: str, states: str = "", templates: str = "[]\n") -> Path:
    root = tmp_path / "refdata"
    shutil.rmtree(root, ignore_errors=True)
    (root / "values").mkdir(parents=True)
    (root / "templates").mkdir()
    (root / "values" / "test.yaml").write_text("\n".join(entries))
    (root / "templates" / "index.yaml").write_text(templates)
    if states:
        (root / "state_codes.yaml").write_text(states)
    return root


def problems(root) -> str:
    with pytest.raises(RefdataInvalid) as e:
        read_files(root)
    return "\n".join(e.value.problems)


# --- files ------------------------------------------------------------------------


def test_the_repository_files_are_valid():
    files = read_files(REPO_REFDATA)
    keys = {r.ident for r in files.rows if r.table == "values"}
    assert {"auth.code_ttl_minutes", "gstr1.offline_tool.max_lines", "filing.locked_return_treatment",
            "invoice.number.max_length", "identity.max_owned_businesses"} <= keys
    assert {r.ident for r in files.rows if r.table == "state_codes"} >= {"19", "27", "96", "97"}
    assert main(["check", str(REPO_REFDATA)]) == 0


def test_every_repository_row_cites_a_source_and_tax_rows_are_not_po_confirmed():
    for r in read_files(REPO_REFDATA).rows:
        assert r.metadata["source_url"] and r.metadata["source_title"] and r.metadata["last_checked"]
        if r.table == "state_codes" or r.columns.get("kind") == "tax":
            assert r.metadata["status"] != "po_confirmed"


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda e: e.replace("  source_url: https://example.org/source\n", ""), "source_url is required"),
        (lambda e: e.replace("https://example.org/source", "http://example.org"), "https:// link"),
        (lambda e: e.replace('value: "5"', "value: 5"), "quoted string"),
        (lambda e: e.replace('value: "5"', 'value: "5.5"'), "not an integer"),
        (lambda e: e.replace("type: integer", "type: float"), "type must be one of"),
        (lambda e: e.replace("kind: product", "kind: ops"), "kind must be tax or product"),
        (lambda e: e.replace("status: provisional", "status: expert_confirmed"), "not allowed for kind product"),
        (lambda e: e.replace("key: test.limit", "key: Test Limit"), "dotted lower-case"),
        (lambda e: e.replace("valid_from: 2026-01-01", "valid_from: 2026-01-01\n  valid_to: 2025-01-01"),
         "valid_to must be after valid_from"),
        (lambda e: e + "  colour: blue\n", "unknown fields"),
    ],
)
def test_an_invalid_entry_fails_the_whole_file_check(tmp_path, change, message):
    entry = ENTRY.format(value="5", valid_from="2026-01-01")
    assert message in problems(tree(tmp_path, change(entry)))


def test_tax_rows_take_expert_or_ca_status_only(tmp_path):
    tax = ENTRY.format(value="5", valid_from="2026-01-01").replace("kind: product", "kind: tax")
    assert "not allowed for kind tax" in problems(tree(tmp_path, tax.replace("provisional", "po_confirmed")))
    read_files(tree(tmp_path, tax.replace("provisional", "ca_confirmed") + CONFIRMED))


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        ("", "needs confirmed_by"),
        ('  confirmed_by: "GST expert"\n', "needs confirmed_on"),
        ('  confirmed_by: "  "\n  confirmed_on: 2026-10-20\n', "needs confirmed_by"),
        ('  confirmed_by: "GST expert"\n  confirmed_on: 2999-01-01\n', "is in the future"),
    ],
)
def test_a_confirmed_row_names_who_confirmed_it_and_when(tmp_path, extra, message):
    tax = ENTRY.format(value="5", valid_from="2026-01-01").replace("kind: product", "kind: tax")
    assert message in problems(tree(tmp_path, tax.replace("provisional", "expert_confirmed") + extra))


def test_a_provisional_row_names_nobody(tmp_path):
    entry = ENTRY.format(value="5", valid_from="2026-01-01") + CONFIRMED
    assert "a provisional row has no confirmed_by" in problems(tree(tmp_path, entry))


def test_a_confirmed_template_names_who_confirmed_it(tmp_path):
    root = tree(tmp_path, ENTRY.format(value="5", valid_from="2026-01-01"))
    (root / "templates" / "t.xlsx").write_bytes(b"template bytes")
    index = (
        "- key: t\n  version: \"1\"\n  file: t.xlsx\n  sha256: \"{sha}\"\n  source_url: https://example.org/t\n"
        "  last_checked: 2026-10-26\n  status: expert_confirmed\n"
    ).format(sha=hashlib.sha256(b"template bytes").hexdigest())
    (root / "templates" / "index.yaml").write_text(index)
    assert "needs confirmed_by" in problems(root)
    (root / "templates" / "index.yaml").write_text(index + CONFIRMED)
    t = read_files(root).templates[0]
    assert (t.confirmed_by, str(t.confirmed_on)) == ("GST expert, RS-9", "2026-10-20")


def test_patterns_must_compile_and_enums_need_their_allowed_list(tmp_path):
    bad = ENTRY.format(value="[a-", valid_from="2026-01-01").replace("integer", "pattern")
    assert "pattern does not compile" in problems(tree(tmp_path, bad))
    enum = ENTRY.format(value="refuse", valid_from="2026-01-01").replace("integer", "enum")
    assert "enum needs allowed" in problems(tree(tmp_path, enum))
    assert "is not one of" in problems(tree(tmp_path, enum + "  allowed: [roll_forward]\n"))
    read_files(tree(tmp_path, enum + "  allowed: [refuse, roll_forward]\n"))


def test_overlapping_or_duplicate_ranges_for_a_key_are_refused(tmp_path):
    a = ENTRY.format(value="5", valid_from="2026-01-01") + "  valid_to: 2026-06-01\n"
    b = ENTRY.format(value="6", valid_from="2026-03-01")
    assert "overlaps" in problems(tree(tmp_path, a, b))
    assert "two entries from 2026-01-01" in problems(
        tree(tmp_path, ENTRY.format(value="5", valid_from="2026-01-01"), ENTRY.format(value="6", valid_from="2026-01-01"))
    )


def test_a_template_must_match_its_sha256(tmp_path):
    root = tree(tmp_path, ENTRY.format(value="5", valid_from="2026-01-01"))
    (root / "templates" / "t.xlsx").write_bytes(b"template bytes")
    good = hashlib.sha256(b"template bytes").hexdigest()
    index = (
        "- key: t\n  version: \"1\"\n  file: t.xlsx\n  sha256: \"{sha}\"\n  source_url: https://example.org/t\n"
        "  last_checked: 2026-10-26\n  status: provisional\n"
    )
    (root / "templates" / "index.yaml").write_text(index.format(sha="0" * 64))
    assert "index says" in problems(root)
    (root / "templates" / "index.yaml").write_text(index.format(sha=good))
    assert read_files(root).templates[0].sha256 == good


def test_check_cli_reports_problems(tmp_path, capsys):
    root = tree(tmp_path, ENTRY.format(value="x", valid_from="2026-01-01"))
    assert main(["check", str(root)]) == 1
    assert "not an integer" in capsys.readouterr().err


# --- loads ------------------------------------------------------------------------


@pytest.fixture()
def db(tmp_path):
    name = f"r_{uuid.uuid4().hex[:10]}"
    with psycopg.connect(DSN, autocommit=True) as admin:
        admin.execute(f"create database {name}")
        admin.execute("do $$ begin if not exists (select from pg_roles where rolname='rds_iam') then create role rds_iam; end if; end $$")
    root = tmp_path / "migrations"
    collect(root)
    with psycopg.connect(DSN.rsplit("/", 1)[0] + f"/{name}", autocommit=True) as c:
        migrate(c, root)
        yield c
    with psycopg.connect(DSN, autocommit=True) as admin:
        admin.execute(f"drop database {name} with (force)")


def rows(c, key="test.limit"):
    return c.execute(
        "select value, valid_from::text, valid_to::text, status from refdata.values where key = %s order by valid_from",
        (key,),
    ).fetchall()


@needs_pg
def test_the_repository_files_load_and_a_second_load_changes_nothing(db, tmp_path):
    first = load(db, REPO_REFDATA, "sha1")
    assert first["rows_inserted"] == len(read_files(REPO_REFDATA).rows) and first["rows_closed"] == 0
    assert load(db, REPO_REFDATA, "sha2") == {"rows_inserted": 0, "rows_closed": 0, "rows_updated": 0}
    loads = db.execute("select git_sha, rows_inserted, files from refdata.loads order by at").fetchall()
    assert [(g, n) for g, n, _ in loads] == [("sha1", first["rows_inserted"]), ("sha2", 0)]
    assert "values/auth.yaml" in loads[0][2]
    loaded_from = "select loaded_from from refdata.values where key = 'auth.code_ttl_minutes'"
    assert db.execute(loaded_from).fetchone()[0] == "values/auth.yaml@sha1"


@needs_pg
def test_a_new_value_is_a_new_row_that_closes_the_old_one(db, tmp_path):
    load(db, tree(tmp_path, ENTRY.format(value="5", valid_from="2026-01-01")))
    counts = load(
        db,
        tree(tmp_path, ENTRY.format(value="5", valid_from="2026-01-01"), ENTRY.format(value="7", valid_from="2026-11-01")),
    )
    assert counts == {"rows_inserted": 1, "rows_closed": 1, "rows_updated": 0}
    assert rows(db) == [("5", "2026-01-01", "2026-11-01", "provisional"), ("7", "2026-11-01", None, "provisional")]


@needs_pg
def test_an_edited_value_is_refused_and_nothing_is_written(db, tmp_path):
    load(db, tree(tmp_path, ENTRY.format(value="5", valid_from="2026-01-01")))
    before = db.execute("select count(*) from refdata.loads").fetchone()[0]
    with pytest.raises(RefdataInvalid, match="value changed from '5' to '6'"):
        load(db, tree(tmp_path, ENTRY.format(value="6", valid_from="2026-01-01")))
    assert rows(db) == [("5", "2026-01-01", None, "provisional")]
    assert db.execute("select count(*) from refdata.loads").fetchone()[0] == before


@needs_pg
def test_a_removed_row_is_refused(db, tmp_path):
    load(db, tree(tmp_path, ENTRY.format(value="5", valid_from="2026-01-01")))
    other = ENTRY.format(value="1", valid_from="2026-01-01").replace("test.limit", "test.other")
    with pytest.raises(RefdataInvalid, match="no longer in the files"):
        load(db, tree(tmp_path, other))
    assert rows(db, "test.other") == []


@needs_pg
def test_status_and_source_changes_are_updates_counted_in_the_load(db, tmp_path):
    load(db, tree(tmp_path, ENTRY.format(value="5", valid_from="2026-01-01")))
    confirmed = ENTRY.format(value="5", valid_from="2026-01-01").replace("provisional", "po_confirmed") + CONFIRMED
    assert load(db, tree(tmp_path, confirmed))["rows_updated"] == 1
    assert rows(db)[0][3] == "po_confirmed"
    who = "select confirmed_by, confirmed_on::text from refdata.values where key = 'test.limit'"
    assert db.execute(who).fetchone() == ("GST expert, RS-9", "2026-10-20")


@needs_pg
def test_the_database_refuses_a_confirmed_row_that_names_nobody(db):
    insert = (
        "insert into refdata.values (key, value, type, kind, valid_from, source_url, source_title, last_checked,"
        " status, loaded_from, confirmed_by, confirmed_on) values ('x.y', '1', 'integer', 'tax', '2026-01-01',"
        " 'https://e', 't', '2026-01-01', %s, 'test', %s, %s)"
    )
    for status, by, on in (("ca_confirmed", None, None), ("ca_confirmed", " ", "2026-10-20"),
                           ("ca_confirmed", "CA", None), ("provisional", "CA", "2026-10-20")):
        with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
            db.execute(insert, (status, by, on))
    db.execute(insert, ("ca_confirmed", "CA, CA-1", "2026-10-20"))


@needs_pg
def test_the_database_refuses_an_overlap_even_without_the_loader(db):
    db.execute(
        "insert into refdata.values (key, value, type, kind, valid_from, source_url, source_title, last_checked,"
        " status, loaded_from) values ('x.y', '1', 'integer', 'tax', '2026-01-01', 'https://e', 't', '2026-01-01',"
        " 'provisional', 'test')"
    )
    with pytest.raises(psycopg.errors.ExclusionViolation):
        db.execute(
            "insert into refdata.values (key, value, type, kind, valid_from, source_url, source_title, last_checked,"
            " status, loaded_from) values ('x.y', '2', 'integer', 'tax', '2026-06-01', 'https://e', 't', '2026-01-01',"
            " 'provisional', 'test')"
        )


@needs_pg
def test_app_roles_can_read_but_not_write(db):
    load(db, REPO_REFDATA)
    for role in ("app_rw", "app_ro"):
        with db.transaction():
            db.execute(f"set local role {role}")
            assert db.execute("select count(*) from refdata.values").fetchone()[0] > 0
            assert db.execute("select count(*) from refdata.state_codes").fetchone()[0] == 38
        for sql in (
            "update refdata.values set value = '1'",
            "delete from refdata.state_codes",
            "insert into refdata.loads (id, git_sha, files, rows_inserted, rows_closed, rows_updated)"
            " values (gen_random_uuid(), 'x', '{}', 0, 0, 0)",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege), db.transaction():
                db.execute(f"set local role {role}")
                db.execute(sql)


@needs_pg
def test_the_migrator_loads_refdata_after_the_migrations(tmp_path):
    name = f"r_{uuid.uuid4().hex[:10]}"
    with psycopg.connect(DSN, autocommit=True) as admin:
        admin.execute(f"create database {name}")
    root = tmp_path / "migrations"
    collect(root)
    try:
        with psycopg.connect(DSN.rsplit("/", 1)[0] + f"/{name}", autocommit=True) as c:
            migrate(c, root, REPO_REFDATA)
            assert c.execute("select count(*) from refdata.loads").fetchone()[0] == 1
            migrate(c, root, REPO_REFDATA)
            files = c.execute("select files from refdata.loads order by at desc limit 1").fetchone()[0]
            assert files == json.loads(json.dumps(read_files(REPO_REFDATA).hashes))
    finally:
        with psycopg.connect(DSN, autocommit=True) as admin:
            admin.execute(f"drop database {name} with (force)")
