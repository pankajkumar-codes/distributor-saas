"""Workforce: scaling signals, creating instances or new roles, and safe retirement.

Order of preference (brief section 3): assign an existing agent, then activate a suspended
one, then add an instance of an existing role, then (with the owner's approval) a new role.
"""

from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select

from . import tasks as T
from .core import Org, OrgError
from .models import Agent, AgentStatus, Execution, PullRequest, ReviewAssignment, Task
from .models import TaskStatus as S


def instances(org: Org, role: str, *, include_retired: bool = False) -> list[Agent]:
    q = select(Agent).where(Agent.role == role)
    if not include_retired:
        q = q.where(Agent.status != AgentStatus.retired)
    return list(org.session.scalars(q.order_by(Agent.id)))


def create_agent(org: Org, role: str, requested_by: str, *, reason: str, temporary: bool = False,
                 objective: str | None = None, budget_usd: Decimal | None = None,
                 owner_approval: str | None = None) -> Agent:
    """Add one instance. The CEO may add instances of active roles within max_instances; a first
    instance of a template-only role, or going past the cap, needs the owner's approval (a link)."""
    tmpl = org.policy.roles.get(role)
    if tmpl is None:
        raise OrgError("unknown_role", f"no role template {role!r} in policy.toml")
    if not reason:
        raise OrgError("reason_required", "say which unmet need this agent serves")
    if temporary and not objective:
        raise OrgError("objective_required", "a temporary agent needs an objective and an end condition")
    suspended = [a for a in instances(org, role) if a.status == AgentStatus.suspended]
    if suspended:
        agent = suspended[0]
        agent.status = AgentStatus.active
        org.audit(requested_by, "agent_reactivated", f"agent:{agent.id}", reason=reason)
        return agent
    live = instances(org, role)
    needs_owner = (tmpl.template_only and not live) or len(live) >= tmpl.max_instances
    if needs_owner and not owner_approval:
        org.message("APPROVAL_REQUEST", requested_by, "owner",
                    f"Add a {role} agent: {reason}", respond_by=org.now() + timedelta(days=2))
        raise OrgError("owner_approval_required",
                       f"adding {role} needs the owner's approval (new role or over max_instances)")
    n = len(instances(org, role, include_retired=True)) + 1
    agent = Agent(
        id=f"{role}-{n}", name=f"{role.replace('_', ' ').title()} {n}", role=role, department=tmpl.department,
        seniority=tmpl.seniority, capabilities=list(tmpl.capabilities), status=AgentStatus.active,
        max_active_tasks=1 if tmpl.coding else 3, temporary=temporary, objective=objective,
        budget_usd=budget_usd, created_by=requested_by, created_at=org.now(),
    )
    org.session.add(agent)
    org.audit(requested_by, "agent_created", f"agent:{agent.id}", reason=reason, temporary=temporary,
              owner_approval=owner_approval, budget_usd=str(budget_usd) if budget_usd else None)
    org.session.flush()
    return agent


def retire_blockers(org: Org, agent: Agent) -> list[str]:
    out = []
    active = org.session.scalars(select(Task.id).where(
        Task.assignee_id == agent.id, Task.status.not_in([S.DONE, S.CANCELLED, S.BACKLOG]))).all()
    if active:
        out.append(f"owns open tasks: {', '.join(active)}")
    if org.session.scalar(select(Execution.id).where(Execution.agent_id == agent.id, Execution.status == "running")):
        out.append("has a running execution")
    reviews = org.session.scalars(
        select(ReviewAssignment.pr_number).join(PullRequest, PullRequest.number == ReviewAssignment.pr_number)
        .where(ReviewAssignment.reviewer_id == agent.id, ReviewAssignment.active, PullRequest.state == "open")).all()
    if reviews:
        out.append(f"assigned reviews on PRs {', '.join(f'#{n}' for n in reviews)}")
    prs = org.session.scalars(select(PullRequest.number).where(
        PullRequest.author_id == agent.id, PullRequest.state == "open")).all()
    if prs:
        out.append(f"authors open PRs {', '.join(f'#{n}' for n in prs)}")
    return out


def retire(org: Org, agent: Agent, actor: str, *, reason: str, transfer_to: Agent | None = None,
           findings: str = "") -> Agent:
    """Retire without losing work. With transfer_to, open tasks/reviews/PRs move first; history stays."""
    if transfer_to is not None:
        if transfer_to.status != AgentStatus.active or transfer_to.id == agent.id:
            raise OrgError("bad_transfer", "transfer target must be another active agent")
        for task in org.session.scalars(select(Task).where(
                Task.assignee_id == agent.id, Task.status.not_in([S.DONE, S.CANCELLED]))):
            task.assignee_id = transfer_to.id
            task.lease_owner = task.lease_expires_at = None
            org.message("TASK_ASSIGNMENT", actor, transfer_to.id, f"Handed over from {agent.id}: {task.title}",
                        task_id=task.id)
        for pr in org.session.scalars(select(PullRequest).where(
                PullRequest.author_id == agent.id, PullRequest.state == "open")):
            pr.author_id = transfer_to.id
        for ra in org.session.scalars(select(ReviewAssignment).where(
                ReviewAssignment.reviewer_id == agent.id, ReviewAssignment.active)):
            ra.active = False  # the watchdog re-fills the slot with an eligible reviewer
        org.session.flush()
    blockers = retire_blockers(org, agent)
    if blockers:
        raise OrgError("retire_blocked", "; ".join(blockers))
    agent.status, agent.retired_at = AgentStatus.retired, org.now()
    org.audit(actor, "agent_retired", f"agent:{agent.id}", reason=reason, findings=findings,
              transferred_to=transfer_to.id if transfer_to else None)
    return agent


def signals(org: Org) -> list[dict]:
    """Evidence-based scaling and retirement recommendations. Nothing is created automatically."""
    out = []
    now = org.now()
    wait = timedelta(hours=org.policy.workforce["waiting_hours_signal"])
    for task in org.session.scalars(select(Task).where(Task.status == S.READY)):
        if T.unmet_dependencies(org, task.id):
            continue
        ready_since = task.ready_at or task.created_at
        if now - ready_since < wait or T.choose_assignee(org, task) is not None:
            continue  # not sustained, or someone can take it now
        qualified = [a for a in org.session.scalars(select(Agent).where(Agent.status == AgentStatus.active))
                     if set(task.required_capabilities) <= set(a.capabilities)]
        if qualified:
            role = qualified[0].role
            out.append({"signal": "capacity", "task": task.id, "role": role,
                        "recommend": f"add an instance of {role} or reprioritize",
                        "evidence": f"ready {now - ready_since} and all {len(qualified)} qualified agents are full"})
        else:
            roles = [r.name for r in org.policy.roles.values()
                     if set(task.required_capabilities) <= set(r.capabilities)]
            out.append({"signal": "capability_gap", "task": task.id, "roles": roles,
                        "recommend": f"activate {roles[0]} (needs owner approval)" if roles
                        else "no role template has these capabilities",
                        "evidence": f"needs {task.required_capabilities}; no active agent has them"})
    per = org.policy.workforce["review_queue_per_reviewer"]
    for agent in org.session.scalars(select(Agent).where(Agent.status == AgentStatus.active)):
        from .reviews import _review_load
        load = _review_load(org, agent.id)
        if load > per:
            out.append({"signal": "review_queue", "agent": agent.id, "role": agent.role,
                        "recommend": f"add a reviewer of role {agent.role} or rebalance",
                        "evidence": f"{load} open review assignments > {per}"})
    idle = timedelta(days=org.policy.workforce["idle_days_before_retire_review"])
    for agent in org.session.scalars(select(Agent).where(Agent.status == AgentStatus.active)):
        last = agent.last_activity_at or agent.created_at
        if now - last > idle and not retire_blockers(org, agent) and len(instances(org, agent.role)) > 1:
            out.append({"signal": "idle", "agent": agent.id, "role": agent.role,
                        "recommend": "consider retiring or suspending this instance",
                        "evidence": f"no activity since {last:%Y-%m-%d}; another {agent.role} exists"})
        if agent.temporary and not retire_blockers(org, agent) and now - last > timedelta(days=1):
            out.append({"signal": "temporary_done", "agent": agent.id, "role": agent.role,
                        "recommend": "retire the temporary agent and keep its findings",
                        "evidence": f"objective: {agent.objective}"})
    return out
