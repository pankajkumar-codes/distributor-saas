"""Task lifecycle: validated transitions, dependencies, leases and evidence-backed completion."""

from datetime import timedelta

from sqlalchemy import select

from .core import Org, OrgError
from .models import Agent, AgentStatus, PullRequest, Task, TaskDependency, TaskEvent
from .models import TaskStatus as S

TRANSITIONS: dict[S, set[S]] = {
    S.BACKLOG: {S.READY, S.CANCELLED},
    S.READY: {S.ASSIGNED, S.BACKLOG, S.BLOCKED, S.CANCELLED},
    S.ASSIGNED: {S.IN_PROGRESS, S.READY, S.BLOCKED, S.CANCELLED},
    S.IN_PROGRESS: {S.IN_REVIEW, S.BLOCKED, S.READY, S.DONE, S.CANCELLED},
    S.BLOCKED: {S.READY, S.ASSIGNED, S.IN_PROGRESS, S.CANCELLED},
    S.IN_REVIEW: {S.CHANGES_REQUESTED, S.APPROVED, S.BLOCKED, S.CANCELLED},
    S.CHANGES_REQUESTED: {S.IN_PROGRESS, S.IN_REVIEW, S.BLOCKED, S.CANCELLED},
    S.APPROVED: {S.DONE, S.CHANGES_REQUESTED, S.IN_REVIEW, S.CANCELLED},
    S.DONE: set(),
    S.CANCELLED: set(),
}
# Work that ships as code must go through review; it can never jump IN_PROGRESS -> DONE.
REVIEWED_TYPES = {"implementation", "bugfix", "infra", "migration"}
# Statuses that hold a coding agent's single implementation slot.
ACTIVE = {S.ASSIGNED, S.IN_PROGRESS, S.CHANGES_REQUESTED}
CLOSED = {S.DONE, S.CANCELLED}


def get_task(org: Org, task_id: str) -> Task:
    task = org.session.get(Task, task_id)
    if task is None:
        raise OrgError("not_found", f"task {task_id} not found")
    return task


def create_task(org: Org, task_id: str, title: str, creator: str, *, depends_on=(), **fields) -> Task:
    if org.session.get(Task, task_id) is not None:
        # Same ID twice is a duplicate, never an overwrite.
        raise OrgError("duplicate", f"task {task_id} already exists")
    if fields.get("parent_id"):
        get_task(org, fields["parent_id"])
    now = org.now()
    task = Task(id=task_id, title=title, creator=creator, status=S.BACKLOG, created_at=now, updated_at=now,
                **fields)
    org.session.add(task)
    org.session.add(TaskEvent(task_id=task_id, at=now, actor=creator, from_status=None, to_status=S.BACKLOG,
                              note="created"))
    org.session.flush()
    for dep in depends_on:
        add_dependency(org, task_id, dep)
    org.touch()
    return task


def dependencies(org: Org, task_id: str) -> list[str]:
    return list(org.session.scalars(select(TaskDependency.depends_on_id).where(TaskDependency.task_id == task_id)))


def add_dependency(org: Org, task_id: str, depends_on_id: str) -> None:
    get_task(org, task_id)
    get_task(org, depends_on_id)
    if task_id == depends_on_id or _reaches(org, depends_on_id, task_id):
        raise OrgError("dependency_cycle", f"{task_id} -> {depends_on_id} would create a cycle")
    if depends_on_id not in dependencies(org, task_id):
        org.session.add(TaskDependency(task_id=task_id, depends_on_id=depends_on_id))
        org.session.flush()


def _reaches(org: Org, start: str, target: str) -> bool:
    seen, stack = set(), [start]
    while stack:
        node = stack.pop()
        if node == target:
            return True
        if node not in seen:
            seen.add(node)
            stack.extend(dependencies(org, node))
    return False


def unmet_dependencies(org: Org, task_id: str) -> list[str]:
    return [d for d in dependencies(org, task_id) if get_task(org, d).status != S.DONE]


def transition(org: Org, task: Task, to: S, actor: str, note: str = "") -> Task:
    current = S(task.status)
    if to not in TRANSITIONS[current]:
        raise OrgError("invalid_transition", f"{task.id}: {current} -> {to} is not allowed")
    if to == S.BLOCKED and not note:
        raise OrgError("blocker_reason_required", "say what the task is blocked on")
    if to in (S.ASSIGNED, S.IN_PROGRESS) and (unmet := unmet_dependencies(org, task.id)):
        raise OrgError("dependencies_unmet", f"{task.id} waits on {', '.join(unmet)}")
    if to == S.DONE:
        _check_done(org, task, current)
    task.status = to
    task.updated_at = org.now()
    task.blocker_reason = note if to == S.BLOCKED else None
    if to == S.READY:
        task.ready_at = org.now()
    if to in CLOSED or to == S.READY:
        task.lease_owner = task.lease_expires_at = None
    if to in (S.READY, S.BACKLOG):
        task.assignee_id = None
    org.session.add(TaskEvent(task_id=task.id, at=org.now(), actor=actor, from_status=current, to_status=to,
                              note=note))
    org.touch()
    return task


def _check_done(org: Org, task: Task, current: S) -> None:
    if not task.completion_evidence:
        # An agent saying "done" is not evidence.
        raise OrgError("evidence_required", f"{task.id} has no completion evidence")
    if current == S.IN_PROGRESS and task.task_type in REVIEWED_TYPES:
        raise OrgError("review_required", f"{task.id} is {task.task_type} work and must be reviewed")
    for number in task.prs:
        pr = org.session.get(PullRequest, number)
        if pr is None or pr.state != "merged":
            raise OrgError("pr_not_merged", f"{task.id}: PR #{number} is not merged")
    open_children = org.session.scalars(
        select(Task.id).where(Task.parent_id == task.id, Task.status.not_in([S.DONE, S.CANCELLED]))
    ).all()
    if open_children:
        raise OrgError("children_open", f"{task.id} has open subtasks: {', '.join(open_children)}")


def add_evidence(org: Org, task: Task, kind: str, value: str, actor: str) -> None:
    """kind: test | completion | commit. Lists are replaced, not mutated, so the ORM sees the change."""
    entry = {"value": value, "by": actor, "at": org.now().isoformat()}
    if kind == "test":
        task.test_evidence = [*task.test_evidence, entry]
    elif kind == "completion":
        task.completion_evidence = [*task.completion_evidence, entry]
    elif kind == "commit":
        task.commits = [*task.commits, value]
    else:
        raise OrgError("bad_evidence_kind", kind)
    org.touch()


# ---- assignment ---------------------------------------------------------------------------


def active_load(org: Org, agent_id: str) -> int:
    return len(org.session.scalars(
        select(Task.id).where(Task.assignee_id == agent_id, Task.status.in_(list(ACTIVE)))
    ).all())


def can_take(org: Org, agent: Agent, task: Task) -> bool:
    if agent.status != AgentStatus.active:
        return False
    if not set(task.required_capabilities) <= set(agent.capabilities):
        return False
    return active_load(org, agent.id) < agent.max_active_tasks


def choose_assignee(org: Org, task: Task) -> Agent | None:
    """Cheapest qualified agent with spare capacity; ties go to the least loaded."""
    candidates = [a for a in org.session.scalars(select(Agent)) if can_take(org, a, task)]
    if not candidates:
        return None
    roles = org.policy.roles
    return min(candidates, key=lambda a: (roles[a.role].cost_tier if a.role in roles else 9,
                                          active_load(org, a.id), a.id))


def assign(org: Org, task: Task, agent: Agent, actor: str) -> Task:
    if not can_take(org, agent, task):
        raise OrgError("agent_unavailable", f"{agent.id} can't take {task.id} (status, skills or capacity)")
    transition(org, task, S.ASSIGNED, actor, f"assigned to {agent.id}")
    task.assignee_id = agent.id
    org.message("TASK_ASSIGNMENT", actor, agent.id, task.title, task_id=task.id)
    return task


def claim_lease(org: Org, task: Task, agent_id: str, minutes: int | None = None) -> bool:
    """Exclusive right to work the task. False if another live lease holds it."""
    now = org.now()
    if task.lease_owner and task.lease_owner != agent_id and task.lease_expires_at and task.lease_expires_at > now:
        return False
    if task.assignee_id != agent_id:
        raise OrgError("not_assignee", f"{agent_id} is not assigned {task.id}")
    task.lease_owner = agent_id
    task.lease_expires_at = now + timedelta(minutes=minutes or org.policy.execution["lease_minutes"])
    org.touch()
    return True


def release_lease(org: Org, task: Task, agent_id: str) -> None:
    if task.lease_owner == agent_id:
        task.lease_owner = task.lease_expires_at = None
        org.touch()


def schedule(org: Org, actor: str = "scheduler", *, optional_paused: bool = False) -> list[tuple[str, str]]:
    """Assign every READY task whose dependencies are done, highest priority first.

    Deterministic: no model call decides who gets what. Returns (task, agent) pairs.
    """
    made = []
    ready = org.session.scalars(select(Task).where(Task.status == S.READY).order_by(Task.priority, Task.created_at))
    for task in ready.all():
        if optional_paused and task.optional:
            continue
        if unmet_dependencies(org, task.id):
            continue
        agent = choose_assignee(org, task)
        if agent is not None:
            assign(org, task, agent, actor)
            made.append((task.id, agent.id))
    return made
