#!/usr/bin/env python3
"""Fail if binary floating point appears in application or library code.

CLAUDE.md rule 7: authoritative money arithmetic is Decimal-only. This walks the AST
(so strings like Decimal("0.01") are fine) and flags float literals, float() calls and
`float` type annotations in every module under app/, migrator/ and libs/, except tests.
Money can reach any module, so files are not chosen by name.

    python scripts/float_guard.py            # check the repo
    python scripts/float_guard.py FILE...    # check specific files

A line can opt out with `# float-ok: <reason>` (the reason is required), which
reviewers must agree with.
"""

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEARCH = ["libs/**/*.py", "app/**/*.py", "migrator/**/*.py"]
OPT_OUT = re.compile(r"#\s*float-ok:\s*\S")


def guarded_files() -> list[Path]:
    files = set()
    for pattern in SEARCH:
        for p in ROOT.glob(pattern):
            # Tests deliberately feed floats in to prove they are rejected.
            if "tests" not in p.relative_to(ROOT).parts:
                files.add(p)
    return sorted(files)


def _isinstance_check(node: ast.AST, parents: dict) -> bool:
    """`isinstance(x, float)` is how money.py rejects floats; allow it."""
    parent = parents.get(node)
    while isinstance(parent, ast.Tuple):
        parent = parents.get(parent)
    return isinstance(parent, ast.Call) and isinstance(parent.func, ast.Name) and parent.func.id == "isinstance"


def check(path: Path) -> list[str]:
    source = path.read_text()
    lines = source.splitlines()
    tree = ast.parse(source, filename=str(path))
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    problems = []
    for node in ast.walk(tree):
        why = None
        if isinstance(node, ast.Constant) and isinstance(node.value, float):
            why = f"float literal {node.value!r}"
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "float":
            why = "float() call"
        elif isinstance(node, ast.Name) and node.id == "float" and not _isinstance_check(node, parents):
            parent = parents.get(node)
            if not (isinstance(parent, ast.Call) and parent.func is node):
                why = "float type"
        if why and not OPT_OUT.search(lines[node.lineno - 1]):
            problems.append(f"{path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}:{node.lineno}: {why}")
    return problems


def main(argv: list[str]) -> int:
    files = [Path(a).resolve() for a in argv] or guarded_files()
    problems = [p for f in files for p in check(f)]
    for p in problems:
        print(p)
    print(f"float guard: {len(files)} file(s) checked, {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
