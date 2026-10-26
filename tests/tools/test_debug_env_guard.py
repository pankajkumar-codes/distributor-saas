"""Debug-only paths must ask auth.debug_env(), which is never true on Lambda (QA-DEF-004).

A bare `platform_env() in DEBUG_ENVS` would turn debug login back on for a Lambda whose
PLATFORM_ENV wrongly says local or test, so it may appear only in auth.py itself.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ALLOWED = ROOT / "libs" / "platform_common" / "platform_common" / "auth.py"
PATTERN = re.compile(r"\bDEBUG_ENVS\b")


def test_only_auth_py_reads_debug_envs():
    offenders = [
        f"{p.relative_to(ROOT)}:{n}"
        for base in ("app", "libs")
        for p in sorted((ROOT / base).rglob("*.py"))
        if p != ALLOWED and "tests" not in p.relative_to(ROOT).parts
        for n, line in enumerate(p.read_text().splitlines(), 1)
        if PATTERN.search(line)
    ]
    assert offenders == [], "use platform_common.auth.debug_env() instead: " + ", ".join(offenders)
