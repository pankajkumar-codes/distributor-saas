"""The `migrations` CI job's structural rules (LLD-0 §7), beside lint.py's
destructive-statement rule.

For every timestamped migration file (grandfathered NNNN_ files are frozen):
- names: YYYYMMDDHHMM_snake_name.sql, and no two files in one module share the
  12-digit prefix;
- business dates: no `current_date`, `now()::date` or similar anywhere in the file,
  function bodies included. SQL never decides a business date; Python's
  Clock.today() does, in IST (LLD-0 §3.5). `default now()` columns are fine;
- row-level security: every CREATE TABLE has ENABLE and FORCE ROW LEVEL SECURITY in
  the same file, unless the table is listed in global_tables.yaml with a reason;
- NO FORCE: a table switched to NO FORCE ROW LEVEL SECURITY is forced again later in
  the same file;
- views: every CREATE VIEW is `with (security_invoker = true)`.

Not yet checked, because what they check doesn't exist yet: "every tenant table calls
platform.apply_tenant_policies" (no such function; tenant files write the policy pair
out) and "run-as master only on allow-listed files" (every file runs as the master
today). Both are listed in docs/TESTING.md.

    python -m migrator.checks path/to/module/migrations/*.sql [...]
"""

import re
import sys
from collections import defaultdict
from pathlib import Path

import yaml

from .lint import Finding, Unterminated, statements

GLOBAL_TABLES = Path(__file__).parent / "global_tables.yaml"
GRANDFATHERED = re.compile(r"^\d{4}_")
NAME = re.compile(r"^\d{12}_[a-z0-9_]+\.sql$")
_IDENT = r'(?:"[^"]+"|[a-z_][a-z0-9_$]*)'
_QUALIFIED = rf"({_IDENT}(?:\.{_IDENT})?)"
CREATE_TABLE = re.compile(rf"^create\s+(?:unlogged\s+)?table\s+(?:if\s+not\s+exists\s+)?{_QUALIFIED}", re.I)
CREATE_VIEW = re.compile(rf"^create\s+(?:or\s+replace\s+)?(?:temp(?:orary)?\s+)?view\s+{_QUALIFIED}", re.I)
SECURITY_INVOKER = re.compile(r"\bsecurity_invoker\s*(=\s*(true|on|1)\b)?", re.I)
RLS = re.compile(rf"^alter\s+table\s+(?:if\s+exists\s+)?(?:only\s+)?{_QUALIFIED}\s+(no\s+)?(enable|force)\s+row\s+level\s+security$", re.I)
# Business dates come from Clock.today() in Python (LLD-0 §3.5, RM4-12).
BUSINESS_DATE = re.compile(
    r"\bcurrent_date\b|\blocaltimestamp\b|\bcurrent_timestamp\s*::\s*date\b|\bnow\s*\(\s*\)\s*::\s*date\b"
    r"|::\s*date\b(?=[^;]*\bnow\s*\()|\bdate\s*\(\s*now\s*\(|\bdate_trunc\s*\(\s*'day'\s*,\s*now\s*\(",
    re.I,
)
_LINE_COMMENT = re.compile(r"--[^\n]*")


def _norm(name: str) -> str:
    name = name.replace('"', "").lower()
    return name if "." in name else f"public.{name}"


def global_tables(path: Path = GLOBAL_TABLES) -> dict[str, str]:
    """table -> reason. Every entry needs a reason (LLD-0 §4.5)."""
    data = yaml.safe_load(path.read_text()) or {}
    out = {}
    for table, reason in data.items():
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError(f"{path.name}: {table} needs a reason")
        out[_norm(table)] = reason
    return out


def check_text(path: str, text: str, globals_: dict[str, str]) -> list[Finding]:
    found: list[Finding] = []
    # Business dates: the whole text minus comments, so function bodies count too.
    for n, raw in enumerate(text.splitlines(), 1):
        code = _LINE_COMMENT.sub("", raw)
        m = BUSINESS_DATE.search(code)
        if m:
            found.append(Finding(path, n, "business date in SQL (use Clock.today() in Python)", raw.strip()))
    try:
        stmts = statements(text)
    except Unterminated as e:
        return [*found, Finding(path, 1, f"can't parse: {e}", "")]
    created: dict[str, int] = {}
    enabled, forced = set(), set()
    unforced: dict[str, int] = {}
    for line, stmt in stmts:
        if m := CREATE_TABLE.match(stmt):
            created[_norm(m.group(1))] = line
        elif m := CREATE_VIEW.match(stmt):
            head = stmt.split(" as ", 1)[0] if " as " in stmt.lower() else stmt
            if not SECURITY_INVOKER.search(head) or re.search(r"security_invoker\s*=\s*(false|off|0)\b", head, re.I):
                found.append(Finding(path, line, "view without security_invoker = true", stmt[:120]))
        elif m := RLS.match(stmt):
            table, no, what = _norm(m.group(1)), bool(m.group(2)), m.group(3).lower()
            if what == "enable" and not no:
                enabled.add(table)
            elif what == "force":
                if no:
                    unforced[table] = line
                    forced.discard(table)
                else:
                    forced.add(table)
                    unforced.pop(table, None)
    for table, line in sorted(created.items()):
        if table in globals_:
            continue
        missing = [w for w, s in (("ENABLE", enabled), ("FORCE", forced)) if table not in s]
        if missing:
            found.append(Finding(
                path, line, f"table without {' and '.join(missing)} ROW LEVEL SECURITY "
                "(or list it in migrator/migrator/global_tables.yaml with a reason)", table))
    for table, line in sorted(unforced.items()):
        found.append(Finding(path, line, "NO FORCE ROW LEVEL SECURITY not forced again in the same file", table))
    return found


def _module(p: Path) -> str:
    """app/src/app/modules/<module>/migrations/x.sql, libs/platform_common/migrations (as
    "platform"), or the migrator zip's migrations/<module>/x.sql."""
    if p.parent.name == "migrations":
        return "platform" if p.parent.parent.name == "platform_common" else p.parent.parent.name
    return p.parent.name


def check(paths: list[Path], globals_: dict[str, str] | None = None) -> list[Finding]:
    globals_ = global_tables() if globals_ is None else globals_
    found: list[Finding] = []
    prefixes: dict[tuple[str, str], list[str]] = defaultdict(list)
    for p in sorted(set(paths)):
        if GRANDFATHERED.match(p.name):
            continue
        module = _module(p)
        rel = f"{module}/{p.name}"
        if not NAME.match(p.name):
            found.append(Finding(rel, 1, "name must be YYYYMMDDHHMM_snake_name.sql", p.name))
            continue
        prefixes[(module, p.name[:12])].append(p.name)
        found += check_text(rel, p.read_text(), globals_)
    for (module, prefix), names in sorted(prefixes.items()):
        if len(names) > 1:
            found.append(Finding(module, 1, f"two files share the prefix {prefix}", ", ".join(sorted(names))))
    return found


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    findings = check([Path(a) for a in argv])
    for f in findings:
        print(f"{f.path}:{f.line}: {f.rule}: {f.statement}")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
