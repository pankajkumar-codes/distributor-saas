"""Destructive-statement rule of the migration lint (LLD-0 §5). No database."""

from pathlib import Path

import pytest

from migrator.lint import check_text, main, statements

FIXTURES = Path(__file__).parent / "fixtures"
HEADER = "-- destructive: approved by CEO 2026-10-24\n"


def rules(sql: str) -> list[str]:
    return [f.rule for f in check_text(sql)]


def test_lld6_closure_trigger_replacement_needs_no_header():
    # build-readiness 2.5: CREATE OR REPLACE FUNCTION is not destructive, and the
    # words "drop" and "delete" inside bodies, comments and strings don't count.
    assert check_text((FIXTURES / "closure_guard_replacement.sql").read_text()) == []


@pytest.mark.parametrize(
    "sql, rule",
    [
        ("drop function identity.guard_owner_rows();", "DROP"),
        ("DROP TRIGGER guard_owner_rows ON identity.memberships;", "DROP"),
        ("drop policy member_audit on identity.audit_events;", "DROP"),
        ("truncate identity.audit_events;", "TRUNCATE"),
        ("delete from identity.invites;", "DELETE without WHERE"),
        ("alter table identity.users drop column phone;", "ALTER ... DROP COLUMN"),
        ("alter table identity.users drop phone;", "ALTER ... DROP COLUMN"),
        ("alter table identity.users drop if exists phone;", "ALTER ... DROP COLUMN"),
        ("alter type identity.role_t rename value 'viewer' to 'ca';", "ALTER TYPE"),
        (
            "alter table sales.lines alter column qty type numeric(18,3);",
            "ALTER COLUMN ... TYPE",
        ),
        (
            "alter table sales.lines alter qty set data type numeric;",
            "ALTER COLUMN ... TYPE",
        ),
        ("do $$ begin delete from identity.invites; end $$;", "DELETE without WHERE"),
        ("do $body$ begin perform 1; drop table t; end $body$;", "DROP"),
        # review on PR #15 (Staff 2): each of these used to pass silently
        ("insert into t values (E'it\\'s'); drop table t;", "DROP"),
        ("do $$ begin execute 'drop table t'; end $$;", "EXECUTE (dynamic SQL)"),
        (
            "do $$ begin if true then execute format('x'); end if; end $$;",
            "EXECUTE (dynamic SQL)",
        ),
        (
            "with gone as (delete from t returning id) select * from gone where id > 0;",
            "DELETE without WHERE",
        ),
        (
            "insert into log select * from (delete from t returning *) d;",
            "DELETE without WHERE",
        ),
        (
            "insert into t values ('never closed); drop table t;",
            "unparseable (fails closed)",
        ),
        ("do $$ begin drop table t; end;", "unparseable (fails closed)"),
        ("/* never closed\ndrop table t;", "unparseable (fails closed)"),
    ],
)
def test_destructive_statements_need_the_header(sql, rule):
    assert rules(sql) == [rule]
    assert rules(HEADER + sql) == []


@pytest.mark.parametrize(
    "sql",
    [
        "delete from identity.invites where expires_at < now();",
        "alter table t drop constraint t_pkey;",
        "alter table t alter column c drop default;",
        "alter table t alter column c drop not null;",
        "create or replace view identity.v_members with (security_invoker) as select 1;",
        "insert into t values ('drop table x; truncate y');",
        "-- drop table t;\n/* truncate t; */ select 1;",
        "create function f() returns void language sql as $$ delete from t $$;",
    ],
)
def test_non_destructive_statements_pass(sql):
    assert rules(sql) == []


def test_header_counts_only_before_the_first_statement():
    in_body = (
        "create function f() returns void language plpgsql as $$\n"
        "-- destructive: approved by x 2026-01-01\n"
        "begin null; end $$;\n"
        "drop table t;\n"
    )
    assert rules(in_body) == ["DROP"]
    late = "select 1;\n-- destructive: approved by CEO 2026-10-24\ndrop table t;\n"
    assert rules(late) == ["DROP"]
    leading = "-- Purpose of this file\n\n-- destructive: approved by CEO 2026-10-24\n\ndrop table t;\n"
    assert rules(leading) == []


def test_e_strings_and_standard_strings():
    # a backslash only escapes inside E''; in a standard string it is a literal
    assert rules("insert into t values (E'a\\\\', 'b\\'); select 1;") == []
    assert rules("insert into t values (note'x'); select 1;") == []


def test_comment_text_is_not_scanned():
    assert rules("comment on table t is $$ old rows; drop table t; are gone $$;") == []


def test_cte_delete_with_its_own_where_passes():
    assert rules("with gone as (delete from t where id < 5 returning id) select * from gone;") == []


def test_header_needs_who_and_date():
    assert rules("-- destructive: approved\ndrop table t;") == ["DROP"]
    assert rules("-- destructive: approved by CEO\ndrop table t;") == ["DROP"]


def test_reports_the_statement_line():
    sql = "create table t (id int);\n\n-- note\ndrop table t;\n"
    assert [f.line for f in check_text(sql)] == [4]


def test_statement_split_keeps_do_bodies_and_blanks_routine_bodies():
    stmts = [
        s for _, s in statements("create function f() returns int as $f$ select 1; $f$; do $$ begin null; end $$;")
    ]
    assert "select 1" not in " ".join(stmts)
    assert "begin null" in stmts


def test_cli_skips_grandfathered_files(tmp_path, capsys):
    old = tmp_path / "0004_identity_rls_fixes.sql"
    old.write_text("drop policy p on t;")
    new = tmp_path / "202610250000_identity_closure.sql"
    new.write_text("drop policy p on t;")
    assert main([str(old)]) == 0
    assert main([str(new)]) == 1
    assert "202610250000_identity_closure.sql:1: DROP" in capsys.readouterr().out
