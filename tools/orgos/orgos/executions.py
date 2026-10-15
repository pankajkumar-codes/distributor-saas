"""Bounded agent runs, recovery after interruption, and spend controls.

Usage numbers are only ever what a provider reported for a run. When nothing was reported
the run says "unavailable" and is left out of every total; nothing is estimated silently.
"""

from datetime import timedelta
from decimal import Decimal

from sqlalchemy import func, select

from . import tasks as T
from .core import Org, OrgError
from .models import Agent, Execution, Task
from .models import TaskStatus as S

RUNNING = "running"


def month_spend(org: Org) -> Decimal | None:
    """Measured spend this calendar month, or None when no run reported usage."""
    start = org.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    costs = org.session.scalars(
        select(Execution.cost_usd).where(Execution.usage_source == "measured", Execution.started_at >= start)
    ).all()
    costs = [c for c in costs if c is not None]
    return sum(costs, Decimal(0)) if costs else None


def budget_state(org: Org) -> dict:
    limit, spent = org.policy.monthly_limit, month_spend(org)
    state = {"limit_usd": limit, "spent_usd": spent, "optional_paused": False, "hard_stop": False,
             "note": None}
    if limit is None:
        state["note"] = "No monthly limit configured (policy.toml [budget])."
    if spent is None:
        state["note"] = (state["note"] or "") + " No measured usage has been reported yet."
    if limit is not None and spent is not None:
        pct = spent * 100 / limit
        b = org.policy.raw["budget"]
        state["used_pct"] = pct
        state["optional_paused"] = pct >= Decimal(b["optional_pause_pct"])
        state["hard_stop"] = pct >= Decimal(b["hard_stop_pct"])
    return state


def start(org: Org, task: Task, agent: Agent, *, budget_usd: Decimal | None = None,
          max_tool_calls: int | None = None, timeout_minutes: int | None = None) -> Execution:
    if org.session.scalar(select(Execution.id).where(Execution.task_id == task.id, Execution.status == RUNNING)):
        raise OrgError("already_running", f"{task.id} already has a running execution")
    budget = budget_state(org)
    if budget["hard_stop"] and task.priority > 2:
        raise OrgError("budget_hard_stop", "monthly limit reached; only priority 1-2 work may run")
    if budget["optional_paused"] and task.optional:
        raise OrgError("budget_optional_paused", "optional work is paused near the monthly limit")
    if not T.claim_lease(org, task, agent.id):
        raise OrgError("leased", f"{task.id} is leased by {task.lease_owner}")
    attempts = org.session.scalar(select(func.count()).select_from(Execution).where(Execution.task_id == task.id))
    if attempts > org.policy.execution["max_retries"]:
        raise OrgError("retry_limit", f"{task.id} already ran {attempts} times")
    if S(task.status) in (S.ASSIGNED, S.CHANGES_REQUESTED, S.BLOCKED):
        T.transition(org, task, S.IN_PROGRESS, agent.id, "execution started")
    now = org.now()
    run = Execution(
        task_id=task.id, agent_id=agent.id, attempt=attempts + 1, status=RUNNING, started_at=now,
        deadline_at=now + timedelta(minutes=timeout_minutes or org.policy.execution["timeout_minutes"]),
        budget_usd=budget_usd if budget_usd is not None else org.policy.default_execution_budget,
        max_tool_calls=max_tool_calls or org.policy.execution["max_tool_calls"],
    )
    org.session.add(run)
    agent.last_activity_at = now
    org.touch()
    org.session.flush()
    return run


def record_usage(org: Org, run: Execution, *, cost_usd: Decimal | None = None, input_tokens: int | None = None,
                 output_tokens: int | None = None, model: str | None = None, tool_calls: int = 0) -> None:
    """Add provider-reported usage. Stops the run if it goes over its budget or tool-call cap."""
    if run.status != RUNNING:
        raise OrgError("not_running", f"execution {run.id} is {run.status}")
    if cost_usd is not None or input_tokens is not None:
        run.usage_source = "measured"
        run.cost_usd = (run.cost_usd or Decimal(0)) + (cost_usd or Decimal(0))
        run.input_tokens = (run.input_tokens or 0) + (input_tokens or 0)
        run.output_tokens = (run.output_tokens or 0) + (output_tokens or 0)
        run.model = model or run.model
    run.tool_calls += tool_calls
    if run.budget_usd is not None and run.cost_usd is not None and run.cost_usd > run.budget_usd:
        fail(org, run, f"budget exceeded: {run.cost_usd} > {run.budget_usd} USD")
    elif run.max_tool_calls is not None and run.tool_calls > run.max_tool_calls:
        fail(org, run, f"tool-call cap exceeded: {run.tool_calls} > {run.max_tool_calls}")
    org.touch()


def finish(org: Org, run: Execution, result: str) -> None:
    if run.status != RUNNING:
        raise OrgError("not_running", f"execution {run.id} is {run.status}")
    run.status, run.ended_at, run.result = "succeeded", org.now(), result
    task = org.session.get(Task, run.task_id)
    T.release_lease(org, task, run.agent_id)
    org.touch()


def fail(org: Org, run: Execution, error: str, *, status: str = "failed") -> None:
    """Bounded retry: the task goes back to its assignee while retries remain, else BLOCKED + escalation."""
    run.status, run.ended_at, run.error = status, org.now(), error
    task = org.session.get(Task, run.task_id)
    T.release_lease(org, task, run.agent_id)
    attempts = org.session.scalar(select(func.count()).select_from(Execution).where(Execution.task_id == task.id))
    if S(task.status) not in (S.IN_PROGRESS, S.ASSIGNED, S.CHANGES_REQUESTED):
        return
    if attempts <= org.policy.execution["max_retries"]:
        org.audit("orgos", "execution_retry_allowed", f"task:{task.id}", attempt=run.attempt, error=error)
    else:
        T.transition(org, task, S.BLOCKED, "orgos", f"failed {attempts} times; last error: {error}")
        org.message("ESCALATION", "orgos", "em", f"{task.id} failed {attempts} times: {error}", task_id=task.id)
    org.touch()


def recover(org: Org) -> list[int]:
    """Run after a restart and on every tick: time out runs past their deadline, free expired leases."""
    now = org.now()
    timed_out = []
    for run in org.session.scalars(select(Execution).where(Execution.status == RUNNING, Execution.deadline_at < now)):
        fail(org, run, "deadline passed with no result (interrupted or hung)", status="timed_out")
        timed_out.append(run.id)
    for task in org.session.scalars(select(Task).where(Task.lease_expires_at < now)):
        task.lease_owner = task.lease_expires_at = None
        org.touch()
    return timed_out
