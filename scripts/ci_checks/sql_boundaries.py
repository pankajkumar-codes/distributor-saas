#!/usr/bin/env python3
"""Module SQL reads other modules' schemas only through v_* views (LLD-0 §7
`boundaries`, L0-7).

Grants don't enforce "views only" for app_ro, so this does. In every module's Python
(tests excluded), each string literal that holds SQL is searched for `<schema>.<name>`
where <schema> is another module's schema. Allowed: `<schema>.v_<name>` (a published
view) and `<schema>.<function>(` (a definer function the owning module published).
Anything else is a direct read or write of another module's table.

The platform schema is platform_common's and every module may use it; a module's own
schema is its own. Migrations are SQL files and are not scanned here.

    python scripts/ci_checks/sql_boundaries.py [repo root]
"""

import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# Module name -> schema it owns (LLD-0 §2). Schemas equal module names today.
MODULES = ("refdata", "identity", "business", "catalog", "sales", "documents", "filing", "insights", "imports")
SQL_HINT = re.compile(r"\b(select|insert|update|delete|from|join)\b", re.I)


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    reference: str


def _pattern(schemas: list[str]) -> re.Pattern:
    return re.compile(rf"\b({'|'.join(schemas)})\.([a-z_][a-z0-9_]*)(\s*\()?", re.I)


def scan(path: Path, rel: str, own: str) -> list[Finding]:
    others = [m for m in MODULES if m != own]
    pattern = _pattern(others)
    found = []
    for node in ast.walk(ast.parse(path.read_text(), filename=rel)):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str) and SQL_HINT.search(node.value)):
            continue
        for m in pattern.finditer(node.value):
            schema, name, call = m.group(1), m.group(2), m.group(3)
            if name.startswith("v_") or call:
                continue
            found.append(Finding(rel, node.lineno, f"{schema}.{name}"))
    return found


def check(root: Path) -> list[Finding]:
    found = []
    base = root / "app" / "src" / "app" / "modules"
    for module_dir in sorted(p for p in base.iterdir() if p.is_dir() and p.name in MODULES):
        for p in sorted(module_dir.rglob("*.py")):
            if "tests" in p.relative_to(module_dir).parts:
                continue
            found += scan(p, p.relative_to(root).as_posix(), module_dir.name)
    return found


def main(argv: list[str]) -> int:
    root = Path(argv[0]) if argv else Path(__file__).resolve().parents[2]
    findings = check(root)
    for f in findings:
        print(f"{f.path}:{f.line}: reads {f.reference} directly; use that module's v_* view or interface")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
