"""Apply every service's migrations to a local PostgreSQL, the same way the
migrator Lambda does in AWS.

    python -m migrator.local postgresql://postgres:local-only@localhost:5432/saas

Locally there is no IAM database auth, so this also gives each login role
(svc_<service>, app_rw, app_retention) the password "local-only". Never run this
against AWS.
"""

import sys
import tempfile
from pathlib import Path

import psycopg
from psycopg import sql

from .handler import migrate

SERVICES_DIR = Path(__file__).resolve().parents[2]
LOCAL_PASSWORD = "local-only"


def collect(root: Path) -> None:
    for svc_dir in SERVICES_DIR.iterdir():
        migrations = svc_dir / "migrations"
        if migrations.is_dir():
            (root / svc_dir.name).mkdir(parents=True, exist_ok=True)
            for f in migrations.glob("*.sql"):
                (root / svc_dir.name / f.name).write_text(f.read_text())


def main(dsn: str) -> None:
    if "rds.amazonaws.com" in dsn:
        sys.exit("refusing to run the local migrator against RDS")
    with psycopg.connect(dsn, autocommit=True) as conn:
        # RDS provides this role; plain PostgreSQL does not.
        conn.execute(
            "do $$ begin if not exists (select from pg_roles where rolname = 'rds_iam') "
            "then create role rds_iam; end if; end $$"
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            collect(root)
            applied = migrate(conn, root)
        roles = [
            r
            for (r,) in conn.execute(
                "select rolname from pg_roles "
                "where rolname like 'svc\\_%' or rolname in ('app_rw', 'app_retention') order by rolname"
            )
        ]
        for role in roles:
            conn.execute(sql.SQL("alter role {} password {}").format(sql.Identifier(role), sql.Literal(LOCAL_PASSWORD)))
    print("applied:", ", ".join(applied) if applied else "nothing new")
    print("login roles:", ", ".join(roles), f"(password: {LOCAL_PASSWORD})")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
