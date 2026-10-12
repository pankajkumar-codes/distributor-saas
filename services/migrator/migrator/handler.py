"""Applies each service's SQL migrations in order, once, as the RDS master user.

Invoked by the deploy step after Terraform apply. Migrations are packaged into the
zip under migrations/<service>/NNNN_name.sql. A migration that was already applied
with different content stops the run instead of being silently skipped.
"""

import hashlib
import json
import os
from pathlib import Path

import psycopg

SERVICE_ORDER = ["identity", "commerce", "imports", "documents", "reports"]
MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"


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
    for service in SERVICE_ORDER:
        for path in sorted((root / service).glob("*.sql")):
            sql = path.read_text()
            checksum = hashlib.sha256(sql.encode()).hexdigest()
            key = (service, path.name)
            if key in applied:
                if applied[key] != checksum:
                    raise RuntimeError(f"{service}/{path.name} changed after it was applied")
                continue
            yield service, path.name, sql, checksum


def migrate(conn, root: Path = MIGRATIONS_DIR) -> list[str]:
    done = []
    for service, name, sql, checksum in list(pending(conn, root)):
        with conn.transaction():
            conn.execute(sql)
            conn.execute(
                "insert into public.schema_migrations (service, name, checksum) values (%s, %s, %s)",
                (service, name, checksum),
            )
        done.append(f"{service}/{name}")
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
        applied = migrate(conn)
    return {"applied": applied}
