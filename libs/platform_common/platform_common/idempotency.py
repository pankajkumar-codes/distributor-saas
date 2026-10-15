"""Run a mutating operation at most once per idempotency key (Global AC 3).

Each service keeps its own table in its own schema, shaped like this (ADR 0001
section 7) and protected by the same tenant RLS policy as its other tables:

    create table <schema>.idempotency_keys (
        tenant_id uuid not null,
        key varchar(200) not null,
        request_hash char(64) not null,
        response jsonb,
        created_at timestamptz not null default now(),
        primary key (tenant_id, key));

`run_once` must be called inside the same transaction as the work it guards, so the
key and the effect commit or roll back together:

- new key: runs `operation`, stores its JSON-serializable result, returns it;
- same key, same request: returns the stored result without running anything;
- same key, different request: 409, because guessing which one the caller meant
  is exactly what CLAUDE.md rule 10 forbids.

Two concurrent requests with the same key are serialized by the primary key: the
second waits for the first to commit, then gets the stored result (or runs, if the
first rolled back).
"""

import hashlib
import json
import re
import uuid
from collections.abc import Callable
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

MAX_KEY_LENGTH = 200
_TABLE = re.compile(r"^[a-z_][a-z0-9_]*\.idempotency_keys$")


def _default(value: Any) -> str:
    if isinstance(value, Decimal | uuid.UUID):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=_default)


def request_hash(payload: Any) -> str:
    return hashlib.sha256(canonical_json(payload).encode()).hexdigest()


def validate_key(key: str | None) -> str:
    if not key or len(key) > MAX_KEY_LENGTH or not key.isprintable():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Idempotency-Key header is required (1-{MAX_KEY_LENGTH} printable chars)"
        )
    return key


def run_once(
    session: Session,
    table: str,
    tenant_id: uuid.UUID,
    key: str,
    payload: Any,
    operation: Callable[[], Any],
) -> Any:
    if not _TABLE.match(table):
        raise ValueError(f"unexpected idempotency table name: {table!r}")
    key = validate_key(key)
    digest = request_hash(payload)
    inserted = session.execute(
        text(
            f"insert into {table} (tenant_id, key, request_hash) values (:t, :k, :h) "
            "on conflict (tenant_id, key) do nothing returning key"
        ),
        {"t": tenant_id, "k": key, "h": digest},
    ).first()
    if inserted is None:
        stored_hash, response = session.execute(
            text(f"select request_hash, response from {table} where tenant_id = :t and key = :k"),
            {"t": tenant_id, "k": key},
        ).one()
        if stored_hash != digest:
            raise HTTPException(status.HTTP_409_CONFLICT, "idempotency key reused with a different request")
        return response

    result = operation()
    session.execute(
        text(f"update {table} set response = cast(:r as jsonb) where tenant_id = :t and key = :k"),
        {"r": canonical_json(result), "t": tenant_id, "k": key},
    )
    return json.loads(canonical_json(result))
