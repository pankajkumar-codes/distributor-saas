"""Applies each module's SQL migrations in order, once, as the RDS master user.

bootstrap.sql (the cluster-wide roles, LLD-0 §4.1) runs before the ledger files and
again after them, on every run: the second pass adds grants to roles that the ledger
files have just created.

Invoked by the deploy step after Terraform apply. Migrations are packaged into the
zip under migrations/<module>/<name>.sql. A migration that was already applied
with different content stops the run instead of being silently skipped.

Order (LLD-0 L0-4): first the grandfathered NNNN_ files, module by module; then
every YYYYMMDDHHMM_ file from every module, by (timestamp, module order). The
ledger key stays (service, name) with service = module name, so files moved by the
S0a restructure keep their keys and checksums.
"""

import hashlib
import json
import logging
import os
import re
from pathlib import Path

import psycopg

from . import refdata

# Ties between timestamped files from different modules break in this order.
MODULE_ORDER = [
    "platform", "refdata", "identity", "business", "catalog", "sales", "documents", "filing", "insights", "imports",
]
MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"
REFDATA_DIR = Path(__file__).parent.parent / "refdata"
BOOTSTRAP = Path(__file__).parent / "bootstrap.sql"
log = logging.getLogger(__name__)


def bootstrap(conn) -> None:
    with conn.transaction():
        conn.execute(BOOTSTRAP.read_text())


GRANDFATHERED = re.compile(r"^\d{4}_\w+\.sql$")
TIMESTAMPED = re.compile(r"^\d{12}_\w+\.sql$")


def ordered(root: Path) -> list[tuple[str, Path]]:
    files = [(d.name, f) for d in root.iterdir() if d.is_dir() for f in d.glob("*.sql")]
    unknown = sorted({m for m, _ in files} - set(MODULE_ORDER))
    if unknown:
        raise RuntimeError(f"migrations for unknown modules: {unknown}")
    for m, f in files:
        if not (GRANDFATHERED.match(f.name) or TIMESTAMPED.match(f.name)):
            raise RuntimeError(f"{m}/{f.name}: name must start with NNNN_ or YYYYMMDDHHMM_")
    rank = {m: i for i, m in enumerate(MODULE_ORDER)}
    old = sorted((x for x in files if GRANDFATHERED.match(x[1].name)), key=lambda x: (rank[x[0]], x[1].name))
    new = sorted((x for x in files if TIMESTAMPED.match(x[1].name)), key=lambda x: (x[1].name[:12], rank[x[0]], x[1].name))
    return old + new


def pending(conn, root: Path = MIGRATIONS_DIR):
    conn.execute(
        """create table if not exists public.schema_migrations (
               service text not null,
               name text not null,
               checksum text not null,
               applied_at timestamptz not null default now(),
               primary key (service, name))"""
    )
    applied = {
        (s, n): c for s, n, c in conn.execute("select service, name, checksum from public.schema_migrations")
    }
    for service, path in ordered(root):
        sql = path.read_text()
        checksum = hashlib.sha256(sql.encode()).hexdigest()
        key = (service, path.name)
        if key in applied:
            if applied[key] != checksum:
                raise RuntimeError(f"{service}/{path.name} changed after it was applied")
            continue
        yield service, path.name, sql, checksum


def migrate(conn, root: Path = MIGRATIONS_DIR, refdata_root: Path | None = None) -> list[str]:
    """Applies pending files; then, given `refdata_root`, loads refdata (LLD-0 §5)."""
    bootstrap(conn)
    done = []
    for service, name, sql, checksum in list(pending(conn, root)):
        with conn.transaction():
            conn.execute(sql)
            conn.execute(
                "insert into public.schema_migrations (service, name, checksum) values (%s, %s, %s)",
                (service, name, checksum),
            )
        done.append(f"{service}/{name}")
    try:
        bootstrap(conn)
    except Exception:
        # The ledger is committed; only the grants of this pass are missing until the next run.
        log.error("ledger applied (%s), bootstrap pass 2 failed", ", ".join(done) or "nothing new")
        raise
    if refdata_root is not None:
        # Its own transaction: a refused load leaves the applied migrations in place.
        counts = refdata.load(conn, refdata_root)
        log.info("refdata loaded: %s", counts)
    return done


def _master_connection():
    import boto3

    secret = json.loads(
        boto3.client("secretsmanager").get_secret_value(SecretId=os.environ["DB_MASTER_SECRET_ARN"])["SecretString"]
    )
    return psycopg.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ.get("DB_PORT", "5432")),
        dbname=os.environ["DB_NAME"],
        user=secret["username"],
        password=secret["password"],
        sslmode="require",
        autocommit=True,
    )


def handler(event, context):  # noqa: ARG001
    with _master_connection() as conn:
        applied = migrate(conn, MIGRATIONS_DIR, REFDATA_DIR)
    return {"applied": applied}
