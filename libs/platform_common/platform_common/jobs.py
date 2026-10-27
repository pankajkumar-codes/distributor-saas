"""Jobs (LLD-0 §3.7, HLD §7, TD-3).

A route creates a job in its own unit of work; the job and its `job.run` outbox row
commit together:

    job_id = jobs.create(uow, "imports.parse", natural_key=str(upload_id))

A module registers the handler at import time. It runs in a tenant unit of work rebuilt
from the job's business and the user who created it, so row-level security applies to
everything it reads and writes (HLD §10 boundary 4). Its return value (IDs and counts,
never data: every role of the business can read it) becomes the job's result:

    @jobs.handler("imports.parse")
    def parse(ctx: jobs.JobContext) -> dict:
        ctx.progress(0, rows)
        ...
        return {"run_id": str(run_id)}

How a message is handled (`handle_message`, called by the worker for each SQS message):
1. Claim the job by ID through platform.claim_job. No row means another delivery holds
   it or it is finished: acknowledge and do nothing (AC-9). The message's business and
   type are never trusted; only what the claim returns.
2. Past `MAX_ATTEMPTS`, or a type no handler is registered for: mark it failed.
3. Run the handler and mark the job done in the same transaction, so the result and the
   status commit together.
4. `JobFailed` marks it failed with its code (a bad file, nothing to retry). Any other
   exception rolls the handler's work back and marks it failed_retryable, or failed on
   the last attempt; the worker then reports the message as failed so SQS delivers it
   again after its visibility timeout. After five receives SQS moves it to the DLQ.
"""

import json
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import text

from . import outbox
from .ids import uuid7
from .uow import Principal, UnitOfWork, _set_context, session_factory, unit_of_work

log = logging.getLogger("platform_common.jobs")

MAX_ATTEMPTS = 5  # matches the jobs queue's maximum receive count (TD-3)
# HLD §7: the lease is the worker Lambda's timeout plus one minute. The worker passes
# its own; this default matches the 15-minute timeout in infra.
DEFAULT_LEASE_SECONDS = 15 * 60 + 60
RUN = "job.run"
RECENT = 20

SKIPPED, DONE, FAILED, RETRY = "skipped", "done", "failed", "retry"


class JobFailed(Exception):
    """A failure that retrying won't fix. `code` is stored as the job's error_code."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class JobContext:
    uow: UnitOfWork
    job_id: uuid.UUID
    attempt: int

    def progress(self, done: int, total: int | None = None) -> None:
        """Record progress in its own short transaction, so the status route sees it
        while the handler's transaction is still open."""
        with session_factory()() as tx, tx.begin():
            _set_context(tx, self.uow.principal)
            tx.execute(
                text("update platform.jobs set progress_done = :d, progress_total = coalesce(:t, progress_total),"
                     " updated_at = now() where id = :id"),
                {"d": done, "t": total, "id": self.job_id},
            )


Handler = Callable[[JobContext], dict | None]
_handlers: dict[str, Handler] = {}


def handler(type_: str) -> Callable[[Handler], Handler]:
    def register(fn: Handler) -> Handler:
        if type_ in _handlers and _handlers[type_] is not fn:
            raise RuntimeError(f"job type {type_!r} already has a handler")
        _handlers[type_] = fn
        return fn

    return register


def registered() -> frozenset[str]:
    return frozenset(_handlers)


def create(uow: UnitOfWork, type_: str, *, natural_key: str | None = None) -> uuid.UUID:
    """Queue a job for the unit of work's business, created by its user. A second create
    with the same (type, natural_key) in the business returns the first job's ID and
    sends nothing."""
    p = uow.principal
    if p.business_id is None:
        raise ValueError("jobs belong to a business; create them in a business unit of work")
    if type_ not in _handlers:
        raise ValueError(f"no handler registered for job type {type_!r}")
    job_id = uuid7()
    inserted = uow.tx.execute(
        text("insert into platform.jobs (id, business_id, type, actor_user_id, natural_key)"
             " values (:id, :b, :type, :actor, :key) on conflict (business_id, type, natural_key) do nothing"
             " returning id"),
        {"id": job_id, "b": p.business_id, "type": type_, "actor": p.user_id, "key": natural_key},
    ).scalar()
    if inserted is None:
        return uow.tx.execute(
            text("select id from platform.jobs where business_id = :b and type = :type and natural_key = :key"),
            {"b": p.business_id, "type": type_, "key": natural_key},
        ).scalar_one()
    outbox.emit(uow, RUN, {"job_id": job_id})
    return job_id


def _finish(principal: Principal, job_id: uuid.UUID, status: str, *, result=None, error_code=None, tx=None) -> None:
    sql = text("update platform.jobs set status = :s, result = cast(:r as jsonb), error_code = :e, updated_at = now()"
               " where id = :id")
    params = {"s": status, "r": None if result is None else json.dumps(result), "e": error_code, "id": job_id}
    if tx is not None:
        tx.execute(sql, params)
        return
    with unit_of_work(principal) as uow:
        uow.tx.execute(sql, params)


def run(job_id: uuid.UUID, *, request_id: str = "job", lease_seconds: int = DEFAULT_LEASE_SECONDS) -> str:
    """Claim and run one job. Returns skipped, done, failed or retry (see the module doc)."""
    with unit_of_work(Principal(user_sub=None, request_id=request_id)) as uow:
        claim = uow.tx.execute(
            text("select business_id, actor_user_id, type, attempt from platform.claim_job(:id, :lease)"),
            {"id": job_id, "lease": lease_seconds},
        ).one_or_none()
    if claim is None:
        return SKIPPED
    principal = Principal(user_sub=None, request_id=request_id, user_id=claim.actor_user_id,
                          business_id=claim.business_id)
    fn = _handlers.get(claim.type)
    if fn is None or claim.attempt > MAX_ATTEMPTS:
        code = "no_handler" if fn is None else "attempts_exhausted"
        log.error("job %s (%s) failed: %s", job_id, claim.type, code, extra={"request_id": request_id})
        _finish(principal, job_id, "failed", error_code=code)
        return FAILED
    try:
        with unit_of_work(principal) as job_uow:
            result = fn(JobContext(job_uow, job_id, claim.attempt))
            _finish(principal, job_id, "done", result=result or {}, tx=job_uow.tx)
        return DONE
    except JobFailed as e:
        _finish(principal, job_id, "failed", error_code=e.code)
        return FAILED
    except Exception:
        last = claim.attempt >= MAX_ATTEMPTS
        log.exception("job %s (%s) attempt %d failed", job_id, claim.type, claim.attempt,
                      extra={"request_id": request_id})
        _finish(principal, job_id, "failed" if last else "failed_retryable", error_code="error")
        return FAILED if last else RETRY


def handle_message(body: dict, *, lease_seconds: int = DEFAULT_LEASE_SECONDS) -> str:
    """One queue message. Only `job.run` exists today; anything else raises, so the
    message goes back to the queue and, in the end, the DLQ, where its alarm is seen."""
    if body.get("type") != RUN:
        raise ValueError(f"unknown message type {body.get('type')!r}")
    return run(uuid.UUID(body["job_id"]), request_id=str(body.get("request_id") or "job"),
               lease_seconds=lease_seconds)


@dataclass(frozen=True)
class JobView:
    id: uuid.UUID
    type: str
    status: str
    attempt: int
    progress_done: int | None
    progress_total: int | None
    result: dict | None
    error_code: str | None
    created_at: object
    updated_at: object


_COLUMNS = ("id, type, status, attempt, progress_done, progress_total, result, error_code, created_at, updated_at")


def get(uow: UnitOfWork, job_id: uuid.UUID) -> JobView | None:
    """A job of the unit of work's business, or None (RLS hides every other business's)."""
    row = uow.tx.execute(
        text(f"select {_COLUMNS} from platform.jobs where id = :id and business_id = :b"),  # noqa: S608
        {"id": job_id, "b": uow.principal.business_id},
    ).one_or_none()
    return None if row is None else JobView(*row)


def recent(uow: UnitOfWork, limit: int = RECENT) -> list[JobView]:
    rows = uow.tx.execute(
        text(f"select {_COLUMNS} from platform.jobs where business_id = :b"  # noqa: S608
             " order by created_at desc, id desc limit :n"),
        {"b": uow.principal.business_id, "n": limit},
    ).all()
    return [JobView(*r) for r in rows]
