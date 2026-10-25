"""Run a mutating request at most once per idempotency key (LLD-0 §3.8, Global AC 3).

Every module shares `platform.idempotency_keys`, keyed by (scope, key): the scope is
the business ID on `/b/{business_id}/...` routes and the user ID on `/me` routes. RLS
shows a row only inside its own business or user's unit of work.

`run_once` must run in the same transaction as the work it guards, so the key and the
effect commit or roll back together:

- new key: runs `operation`, stores its JSON-serializable result, returns it;
- same key, same request: returns the stored result without running anything;
- same key, different request: `Conflict("idempotency_mismatch")`, because guessing
  which one the caller meant is exactly what CLAUDE.md rule 10 forbids.

"Same request" means the same method, route template and body. The same key and body
sent to another route is a different request, not a replay of the first one's answer.

Two concurrent requests with the same key are serialized by the primary key: the
second waits for the first to commit, then gets the stored result (or runs, if the
first rolled back).
"""

import hashlib
import json
import uuid
from collections.abc import Callable
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from .errors import AppError, Conflict

MAX_KEY_LENGTH = 200


def _default(value: Any) -> str:
    if isinstance(value, Decimal | uuid.UUID):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=_default)


def request_hash(method: str, route: str, payload: Any) -> str:
    """The method, the route template (e.g. /api/v1/b/{business_id}/products) and the body."""
    return hashlib.sha256(canonical_json([method.upper(), route, payload]).encode()).hexdigest()


def validate_key(key: str | None) -> str:
    if not key or len(key) > MAX_KEY_LENGTH or not key.isprintable():
        raise AppError(
            "idempotency_key_required",
            f"Idempotency-Key header is required (1-{MAX_KEY_LENGTH} printable characters)",
            field="Idempotency-Key",
        )
    return key


def run_once(
    tx: Session,
    scope: uuid.UUID,
    key: str | None,
    *,
    method: str,
    route: str,
    payload: Any,
    operation: Callable[[], Any],
) -> Any:
    key = validate_key(key)
    digest = request_hash(method, route, payload)
    inserted = tx.execute(
        text(
            "insert into platform.idempotency_keys (scope, key, request_hash) values (:s, :k, :h) "
            "on conflict (scope, key) do nothing returning key"
        ),
        {"s": scope, "k": key, "h": digest},
    ).first()
    if inserted is None:
        stored_hash, response = tx.execute(
            text("select request_hash, response from platform.idempotency_keys where scope = :s and key = :k"),
            {"s": scope, "k": key},
        ).one()
        if stored_hash != digest:
            raise Conflict("idempotency_mismatch", "this Idempotency-Key was already used for a different request")
        return response

    result = operation()
    tx.execute(
        text("update platform.idempotency_keys set response = cast(:r as jsonb) where scope = :s and key = :k"),
        {"r": canonical_json(result), "s": scope, "k": key},
    )
    return json.loads(canonical_json(result))
