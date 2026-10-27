"""The outbox (LLD-0 §3.7, HLD §7, [RM4-13]).

`emit` writes a row in the request's transaction and asks the unit of work to send it
once the transaction commits. The send then marks the row sent in its own short
transaction. If the send or the mark fails, the 1-minute `sweep` sends the row again;
a second delivery is harmless because the worker claims a job before doing anything.

A payload holds IDs only, never data: every key ends in `_id` and every value is a UUID.
The message body adds the outbox row's ID, its business and the request ID.
"""

import json
import logging
import uuid

from sqlalchemy import text

from .ids import uuid7
from .queue import get_queue
from .uow import Principal, UnitOfWork, unit_of_work

log = logging.getLogger("platform_common.outbox")

SWEEP_BATCH = 100

_INSERT = text(
    "insert into platform.outbox (id, business_id, type, payload)"
    " values (:id, :business_id, :type, cast(:payload as jsonb))"
)


def _check_payload(payload: dict) -> dict[str, str]:
    out = {}
    for k, v in payload.items():
        if not k.endswith("_id") or not isinstance(v, uuid.UUID):
            raise ValueError(f"outbox payloads hold IDs only (key *_id, value UUID): {k!r}")
        out[k] = str(v)
    return out


def emit(uow: UnitOfWork, type_: str, payload: dict) -> uuid.UUID:
    """Write an outbox row for the unit of work's business; it is sent after commit."""
    business_id = uow.principal.business_id
    if business_id is None:
        raise ValueError("outbox rows belong to a business; emit inside a business unit of work")
    body = _check_payload(payload)
    row_id = uuid7()
    uow.tx.execute(_INSERT, {"id": row_id, "business_id": business_id, "type": type_, "payload": json.dumps(body)})
    message = {**body, "type": type_, "outbox_id": str(row_id), "business_id": str(business_id),
               "request_id": uow.principal.request_id}
    uow.after_commit(lambda: _send([message]))
    return row_id


def _send(messages: list[dict]) -> None:
    queue = get_queue()
    sent = []
    for m in messages:
        queue.send(m)
        sent.append(uuid.UUID(m["outbox_id"]))
    if sent:
        with unit_of_work(Principal(user_sub=None, request_id="outbox.mark")) as uow:
            uow.tx.execute(text("select platform.mark_outbox_sent(cast(:ids as uuid[]))"), {"ids": sent})


def sweep(max_rows: int = SWEEP_BATCH) -> int:
    """Send rows left unsent for 30 s or more (EventBridge, every minute). Returns the count."""
    with unit_of_work(Principal(user_sub=None, request_id="outbox.sweep")) as uow:
        rows = uow.tx.execute(
            text("select outbox_id, business_id, type, payload from platform.sweep_outbox(:n)"), {"n": max_rows}
        ).all()
    messages = [
        {**r.payload, "type": r.type, "outbox_id": str(r.outbox_id),
         "business_id": None if r.business_id is None else str(r.business_id), "request_id": "outbox.sweep"}
        for r in rows
    ]
    if messages:
        log.warning("outbox sweep resending %d message(s)", len(messages))
        _send(messages)
    return len(messages)
