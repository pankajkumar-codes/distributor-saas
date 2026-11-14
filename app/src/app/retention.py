"""The retention Lambda (LLD-6 §6.1, L6-5; D-041).

Its own function and IAM role, from the same zip as the worker, and the only code that
logs in as `app_retention`. That role can execute the `retention.*` functions and
nothing else, so this module holds no SQL beyond calling them: which rows go, and
whether a rule runs at all (refdata `retention.<rule>.enabled`, shipped false), is
decided in the database.

Events, from the EventBridge schedules (both disabled until the staging decision):
    {"task": "purge_operational"}   hourly: that rule only
    {"task": "retention"}           daily: every rule, in RULES order
    {"task": "purge_drafts"}        that rule only (ops, by hand); likewise "purge_uploads"
Either may add "dry_run": true, which counts without deleting (LLD-6 §6.4), so ops can
check a rule before switching it on.

Each call deletes at most MAX_ROWS rows per table in its own short transaction; while
the function reports `more`, the rule is called again, until BUDGET_SECONDS is spent
(the next run continues). Logs carry the rule name and counts only. A failure is logged
by rule name and exception class, then raised, so the invocation fails and its alarm
fires.

It imports no app module: nothing a module registers can run with this role.
"""

import logging
import time

from sqlalchemy import text

from platform_common import db

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# LLD-6 §6.2's order. Later rules are added here as their tables and functions land; the
# GST purge, when it exists, stays last.
RULES = ("purge_operational", "purge_drafts", "purge_uploads")
MAX_ROWS = 5000
BUDGET_SECONDS = 600


def _call(rule: str, dry_run: bool) -> dict:
    with db.engine().begin() as conn:
        # rule comes from RULES, never from the event
        return conn.execute(
            text(f"select retention.{rule}(:dry_run, :max_rows)"), {"dry_run": dry_run, "max_rows": MAX_ROWS}
        ).scalar_one()


def run(rules=RULES, *, dry_run: bool = False, budget_seconds: int = BUDGET_SECONDS, clock=time.monotonic) -> dict:
    deadline = clock() + budget_seconds
    summary: dict[str, dict] = {}
    for rule in rules:
        totals: dict[str, int | None] = {}
        calls = 0
        while True:
            try:
                out = _call(rule, dry_run)
            except Exception as exc:
                logger.error("retention %s failed: %s", rule, type(exc).__name__)
                raise
            calls += 1
            if out.get("skipped"):
                summary[rule] = {"skipped": out["skipped"]}
                break
            for table, n in out["counts"].items():
                totals[table] = None if n is None else (totals.get(table) or 0) + n
            # A dry run deletes nothing, so calling it again would count the same rows.
            if dry_run or not out["more"] or clock() >= deadline:
                summary[rule] = {"dry_run": dry_run, "calls": calls, "counts": totals, "more": out["more"]}
                break
        logger.info("retention %s: %s", rule, summary[rule])
        if clock() >= deadline:
            break  # the next run continues; a rule left out here has done nothing this time
    return summary


def handler(event, context):  # noqa: ARG001
    task = event.get("task")
    dry_run = event.get("dry_run") is True
    if task == "retention":
        return run(dry_run=dry_run)
    if task in RULES:
        return run((task,), dry_run=dry_run)
    raise ValueError(f"unknown retention task {task!r}")
