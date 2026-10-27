"""AC-13: each LLD-0 §7 check fails on its planted fixture (tests/ci_fixtures/) and
passes on the repository."""

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "ci_fixtures"
sys.path.insert(0, str(ROOT / "migrator"))

from migrator import checks  # noqa: E402


def _script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / "ci_checks" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tax_literals = _script("tax_literals")
sql_boundaries = _script("sql_boundaries")


def repo_migrations():
    return sorted([*ROOT.glob("app/src/app/modules/*/migrations/*.sql"),
                   *ROOT.glob("libs/platform_common/migrations/*.sql")])


def test_migration_checks_fail_on_the_planted_files():
    rules = [f.rule for f in checks.check(sorted((FIXTURES / "migrations").rglob("*.sql")))]
    for expected in ("business date in SQL", "view without security_invoker", "table without ENABLE and FORCE",
                     "table without FORCE", "NO FORCE ROW LEVEL SECURITY not forced again", "name must be",
                     "two files share the prefix"):
        assert any(r.startswith(expected) for r in rules), expected


def test_migration_checks_pass_on_the_repository():
    assert checks.check(repo_migrations()) == []


def test_a_global_table_needs_a_reason(tmp_path):
    (tmp_path / "g.yaml").write_text("refdata.values: ''\n")
    with pytest.raises(ValueError, match="needs a reason"):
        checks.global_tables(tmp_path / "g.yaml")


def test_tax_literals_fail_on_the_planted_file():
    found = {(f.what, f.value) for f in tax_literals.check(FIXTURES / "tax_literals", allowed=set())}
    assert found == {("Decimal literal", "0.18"), ("numeric literal", "250000"),
                     ("date literal", "2025, 9, 22"), ("date string", "2017-07-01")}


def test_tax_literals_pass_on_the_repository_and_every_allowlist_entry_is_used():
    allowed = tax_literals.allowlist()
    assert tax_literals.check(ROOT, allowed) == []
    raw = {(f.path, f.value) for f in tax_literals.check(ROOT, allowed=set())}
    assert allowed <= raw, f"stale allowlist entries: {sorted(allowed - raw)}"


def test_sql_boundaries_fail_on_a_direct_table_read_only():
    found = sql_boundaries.check(FIXTURES / "sql_boundaries")
    assert [f.reference for f in found] == ["sales.invoices"]


def test_sql_boundaries_pass_on_the_repository():
    assert sql_boundaries.check(ROOT) == []


@pytest.mark.skipif(not shutil.which("ruff"), reason="ruff not installed")
def test_the_clock_rule_fails_on_the_planted_file(tmp_path):
    # tests/** is exempt from TID251, so check a copy outside it with the repo's config.
    target = tmp_path / "business.py"
    shutil.copy(FIXTURES / "clock" / "business.py", target)
    out = subprocess.run(["ruff", "check", "--config", str(ROOT / "ruff.toml"), "--output-format", "concise",
                          str(target)], capture_output=True, text=True)
    assert out.returncode == 1
    assert out.stdout.count("TID251") == 4
