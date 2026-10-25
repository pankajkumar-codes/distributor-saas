"""Destructive-statement check for migration files (LLD-0 §5, "Forward only").

A file that contains DROP, TRUNCATE, DELETE without WHERE, ALTER ... DROP COLUMN,
ALTER TYPE or ALTER COLUMN ... TYPE needs a header line

    -- destructive: approved by <who> <YYYY-MM-DD>

and the reviewer checks that the approval exists (CLAUDE.md gate). This is one
rule of the `migrations` CI job; the job's other rules are not here yet.

    python -m migrator.lint path/to/file.sql [...]

The header counts only in the file's leading comment block, before the first
statement.

What is scanned: statements that run when the migration runs, including DO
blocks. Function and procedure bodies, and any other dollar-quoted text, are not
scanned, because creating a function runs nothing; CREATE OR REPLACE FUNCTION is
therefore not destructive. Comments and string literals are ignored.

It fails closed where it can't see what runs: EXECUTE (dynamic SQL) needs the
header, and so does a file with an unterminated string, dollar quote or comment.
Grandfathered NNNN_ files are already applied and frozen by checksum, so the CLI
skips them.
"""

import re
import sys
from dataclasses import dataclass
from pathlib import Path

HEADER = re.compile(
    r"^--\s*destructive:\s*approved by\s+\S.*\b\d{4}-\d{2}-\d{2}\b",
    re.IGNORECASE | re.MULTILINE,
)
GRANDFATHERED = re.compile(r"^\d{4}_")

RULES = [
    ("EXECUTE (dynamic SQL)", re.compile(r"^execute\b", re.IGNORECASE)),
    ("DROP", re.compile(r"^drop\b", re.IGNORECASE)),
    ("TRUNCATE", re.compile(r"^truncate\b", re.IGNORECASE)),
    # COLUMN is optional in ALTER TABLE ... DROP [COLUMN] name
    (
        "ALTER ... DROP COLUMN",
        re.compile(
            r"^alter\b.*\bdrop\s+(column\b|(?!(constraint|default|not|expression|identity)\b)(if\s+exists\s+)?\"?\w)",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    ("ALTER TYPE", re.compile(r"^alter\s+type\b", re.IGNORECASE)),
    (
        "ALTER COLUMN ... TYPE",
        re.compile(
            r"^alter\b.*\balter\s+(column\s+)?\S+\s+(set\s+data\s+)?type\b",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
]

_DOLLAR = re.compile(r"\$([A-Za-z_][A-Za-z_0-9]*)?\$")
# In a DO body a statement can follow BEGIN, THEN, ELSE or LOOP on the same "line".
_PLPGSQL_LEAD = re.compile(r"\b(?:begin|then|else|loop)\b", re.IGNORECASE)
# Only a DO block's body runs now; every other dollar-quoted text is blanked.
_DO = re.compile(r"\bdo(\s+language\s+\w+)?\s*$", re.IGNORECASE)
_DELETE = re.compile(r"\bdelete\s+from\b", re.IGNORECASE)
_WHERE = re.compile(r"\bwhere\b", re.IGNORECASE)
_IDENT_CHAR = re.compile(r"[\w$]")


class Unterminated(ValueError):
    pass


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    rule: str
    statement: str


def statements(text: str) -> list[tuple[int, str]]:
    """Split SQL into (line, statement) pairs with comments and string literals
    blanked. A dollar-quoted body is kept, split into its own statements, when it
    belongs to a DO block, and blanked otherwise (function and procedure bodies,
    COMMENT text). Raises Unterminated if a string, dollar quote or block comment
    never closes."""
    out: list[tuple[int, str]] = []
    buf: list[str] = []
    start = None
    i, line, n = 0, 1, len(text)

    def flush() -> None:
        nonlocal buf, start
        stmt = " ".join("".join(buf).split())
        if stmt:
            out.append((start or line, stmt))
        buf, start = [], None

    while i < n:
        c = text[i]
        if text.startswith("--", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        if text.startswith("/*", i):
            j = text.find("*/", i + 2)
            if j < 0:
                raise Unterminated(f"block comment opened on line {line}")
            j += 2
            line += text.count("\n", i, j)
            i = j
            continue
        if c == "'":
            # E'...' strings take backslash escapes; '' is a quote in any string.
            escapes = i > 0 and text[i - 1] in "eE" and not (i > 1 and _IDENT_CHAR.match(text[i - 2]))
            j = i + 1
            while j < n:
                if (escapes and text[j] == "\\") or text.startswith("''", j):
                    j += 2
                elif text[j] == "'":
                    break
                else:
                    j += 1
            if j >= n:
                raise Unterminated(f"string opened on line {line}")
            line += text.count("\n", i, j)
            buf.append("''")
            i = j + 1
            continue
        m = _DOLLAR.match(text, i)
        if m:
            tag = m.group(0)
            j = text.find(tag, m.end())
            if j < 0:
                raise Unterminated(f"dollar quote {tag} opened on line {line}")
            body = text[m.end() : j]
            body_line = line
            line += text.count("\n", i, j + len(tag))
            if _DO.search("".join(buf)):
                for off, stmt in statements(body):
                    out.append((body_line + off - 1, stmt))
            buf.append("$$")
            i = j + len(tag)
            continue
        if c == ";":
            flush()
        else:
            if start is None and not c.isspace():
                start = line
            buf.append(c)
        if c == "\n":
            line += 1
        i += 1
    flush()
    return out


def leading_comments(text: str) -> str:
    """The comment lines before the first statement (blank lines allowed)."""
    lines = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if stripped.startswith("--"):
            lines.append(stripped)
        elif stripped:
            break
    return "\n".join(lines)


def _delete_without_where(piece: str) -> bool:
    """A DELETE anywhere in the statement (a CTE's included) whose own span, up to
    the parenthesis that closes it or the end of the statement, has no WHERE."""
    for m in _DELETE.finditer(piece):
        depth, end = 0, len(piece)
        for k in range(m.end(), len(piece)):
            if piece[k] == "(":
                depth += 1
            elif piece[k] == ")":
                if depth == 0:
                    end = k
                    break
                depth -= 1
        if not _WHERE.search(piece, m.end(), end):
            return True
    return False


def check_text(text: str, path: str = "<sql>") -> list[Finding]:
    if HEADER.search(leading_comments(text)):
        return []
    try:
        stmts = statements(text)
    except Unterminated as e:
        return [Finding(path, 1, "unparseable (fails closed)", str(e))]
    findings = []
    for line, stmt in stmts:
        for piece in _PLPGSQL_LEAD.split(stmt):
            piece = piece.strip()
            rule = next((r for r, pattern in RULES if pattern.search(piece)), None)
            if rule is None and _delete_without_where(piece):
                rule = "DELETE without WHERE"
            if rule:
                findings.append(Finding(path, line, rule, piece[:80]))
                break
    return findings


def check_file(path: Path) -> list[Finding]:
    return check_text(path.read_text(), str(path))


def main(paths: list[str]) -> int:
    findings = []
    for p in map(Path, paths):
        if GRANDFATHERED.match(p.name):
            continue
        findings += check_file(p)
    for f in findings:
        print(f"{f.path}:{f.line}: {f.rule} needs a '-- destructive: approved by <who> <date>' header: {f.statement}")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
