"""A PostgreSQL test may skip only with a reason that names PG_ADMIN_URL or PG_DSN, because
tests/require_pg.py turns exactly those skips into failures under CI=true or REQUIRE_PG=1.
A skip worded any other way ("no database") would hide a suite in CI again (#67)."""

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT / "tests"))

from require_pg import _PG_VARIABLES  # noqa: E402

# A condition or reason that looks like it's about the database.
_LOOKS_PG = re.compile(r"DSN|ADMIN_URL|PG_|postgres|database", re.IGNORECASE)
_SKIP_DIRS = {"node_modules", "ci_fixtures", "__pycache__", ".venv"}


def _reason(call: ast.Call) -> str:
    for kw in call.keywords:
        if kw.arg in ("reason", "msg"):
            return ast.unparse(kw.value)
    return ast.unparse(call.args[0]) if call.args else ""


def unguarded_skips(source: str, name: str) -> list[str]:
    """`file:line` for each skip that is about PostgreSQL but names neither variable."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = ast.unparse(node.func)
        if func.endswith("mark.skipif"):
            about_pg = bool(node.args) and _LOOKS_PG.search(ast.unparse(node.args[0]))
        elif func == "pytest.skip":
            about_pg = _LOOKS_PG.search(_reason(node))
        else:
            continue
        reason = _reason(node)
        if (about_pg or _LOOKS_PG.search(reason)) and not any(v in reason for v in _PG_VARIABLES):
            found.append(f"{name}:{node.lineno}")
    return found


def _test_files():
    for top in ("app", "libs", "migrator", "tests"):
        for path in (ROOT / top).rglob("*.py"):
            if not _SKIP_DIRS.intersection(path.parts) and (path.name.startswith("test_") or path.name == "conftest.py"):
                yield path


def test_every_postgres_skip_names_a_guarded_variable():
    bad = [hit for p in _test_files() for hit in unguarded_skips(p.read_text(), str(p.relative_to(ROOT)))]
    assert bad == [], f"say PG_ADMIN_URL or PG_DSN in the skip reason: {bad}"


def test_the_check_catches_a_skip_worded_another_way():
    planted = (
        "import pytest\n"
        "pytestmark = pytest.mark.skipif(not DSN, reason='no database')\n"
        "def test_x():\n"
        "    pytest.skip('PostgreSQL not available')\n"
        "ok = pytest.mark.skipif(not ADMIN_URL, reason='PG_ADMIN_URL not set')\n"
        "other = pytest.mark.skipif(not ruff, reason='ruff not installed')\n"
    )
    assert unguarded_skips(planted, "t.py") == ["t.py:2", "t.py:4"]
