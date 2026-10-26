#!/usr/bin/env python3
"""No tax number or date written into code (LLD-0 §7 `tax-literals`, CLAUDE.md rule 12).

Scans the modules that compute or file tax (sales, filing, catalog, imports), tests
excluded, for:
- numeric literals other than 0, 1 and 100;
- Decimal("...") with any value but "0.01" (the paise quantum);
- dates: date(...)/datetime(...) with literal arguments, and "YYYY-MM-DD" strings.
Rates, thresholds, limits and dates belong in refdata/ with a source, read through
app.modules.refdata.value_on.

A finding that isn't a tax rule (a column width, a batch size) goes in
tax_literals_allowlist.yaml with a reason:

    - path: app/src/app/modules/imports/staging.py
      value: "500"
      reason: "rows per lookup batch; not a tax rule"

    python scripts/ci_checks/tax_literals.py [repo root]
"""

import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

MODULES = ("sales", "filing", "catalog", "imports")
ALLOWED_NUMBERS = {0, 1, 100}
ALLOWED_DECIMALS = {"0.01"}
# Column widths are schema, not tax rules: String(20), Enum(..., length=20).
COLUMN_TYPES = {"String", "CHAR", "VARCHAR", "Unicode", "Numeric"}
DATE_STRING = re.compile(r"\b(19|20)\d{2}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])\b")
ALLOWLIST = Path(__file__).with_name("tax_literals_allowlist.yaml")


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    value: str
    what: str


def _name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def scan(path: Path, rel: str) -> list[Finding]:
    tree = ast.parse(path.read_text(), filename=rel)
    found: list[Finding] = []
    skip: set[int] = set()  # constants already reported as part of a call
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = _name(node.func)
            consts = [a for a in node.args if isinstance(a, ast.Constant)]
            if fn in COLUMN_TYPES:
                skip.update(id(a) for a in node.args if isinstance(a, ast.Constant))
            skip.update(id(k.value) for k in node.keywords if k.arg == "length" and isinstance(k.value, ast.Constant))
            if fn == "Decimal" and len(node.args) == 1 and isinstance(node.args[0], ast.Constant):
                value = str(node.args[0].value)
                skip.add(id(node.args[0]))
                if value not in ALLOWED_DECIMALS:
                    found.append(Finding(rel, node.lineno, value, "Decimal literal"))
            elif fn in ("date", "datetime") and consts and len(consts) == len(node.args):
                for c in consts:
                    skip.add(id(c))
                found.append(Finding(rel, node.lineno, ", ".join(str(c.value) for c in consts), "date literal"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or id(node) in skip:
            continue
        v = node.value
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            if v not in ALLOWED_NUMBERS:
                found.append(Finding(rel, node.lineno, repr(v), "numeric literal"))
        elif isinstance(v, str) and DATE_STRING.search(v):
            found.append(Finding(rel, node.lineno, DATE_STRING.search(v).group(0), "date string"))
    return found



def allowlist(path: Path = ALLOWLIST) -> set[tuple[str, str]]:
    entries = yaml.safe_load(path.read_text()) or []
    out = set()
    for e in entries:
        if not (isinstance(e, dict) and e.get("path") and "value" in e and str(e.get("reason", "")).strip()):
            raise ValueError(f"{path.name}: every entry needs path, value and reason: {e!r}")
        out.add((e["path"], str(e["value"])))
    return out


def check(root: Path, allowed: set[tuple[str, str]] | None = None) -> list[Finding]:
    allowed = allowlist() if allowed is None else allowed
    found = []
    for module in MODULES:
        base = root / "app" / "src" / "app" / "modules" / module
        for p in sorted(base.rglob("*.py")):
            rel = p.relative_to(root).as_posix()
            if "tests" in p.relative_to(base).parts:
                continue
            found += [f for f in scan(p, rel) if (f.path, f.value) not in allowed]
    return found


def main(argv: list[str]) -> int:
    root = Path(argv[0]) if argv else Path(__file__).resolve().parents[2]
    findings = check(root)
    for f in findings:
        print(f"{f.path}:{f.line}: {f.what} {f.value}: move it to refdata/ (value_on) or allowlist it with a reason")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
