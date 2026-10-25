#!/usr/bin/env python3
"""Fail if a migration that exists on the base ref is missing or edited here.

The migrator's ledger key is (module, file name) and it refuses a changed checksum,
so moving a file is fine but renaming or editing one is not (LLD-0 §2 step 7, §5).
Files are found in both layouts, so this also checks the S0a restructure itself:
    services/<module>/migrations/*.sql          (before S0a)
    app/src/app/modules/<module>/migrations/*.sql

    python scripts/ci_checks/migration_keys.py origin/main
"""

import hashlib
import subprocess
import sys
from pathlib import PurePosixPath

PATTERNS = ("services/*/migrations/*.sql", "app/src/app/modules/*/migrations/*.sql")


def keys(ref: str | None) -> dict[tuple[str, str], str]:
    if ref:
        listing = subprocess.run(["git", "ls-tree", "-r", "--name-only", ref], capture_output=True, text=True, check=True)
    else:
        listing = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True)
    out = {}
    for name in listing.stdout.splitlines():
        path = PurePosixPath(name)
        if not any(path.match(p) for p in PATTERNS):
            continue
        if ref:
            body = subprocess.run(["git", "show", f"{ref}:{name}"], capture_output=True, check=True).stdout
        else:
            body = open(name, "rb").read()
        out[(path.parts[-3], path.name)] = hashlib.sha256(body).hexdigest()
    return out


def main(base: str) -> int:
    before, after = keys(base), keys(None)
    problems = [f"{m}/{n}: missing" for (m, n) in before if (m, n) not in after]
    problems += [f"{m}/{n}: content changed" for (m, n), c in before.items() if (m, n) in after and after[(m, n)] != c]
    for p in problems:
        print(p)
    print(f"{len(before)} migration keys on {base}, {len(after)} here, {len(problems)} problems")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "origin/main"))
