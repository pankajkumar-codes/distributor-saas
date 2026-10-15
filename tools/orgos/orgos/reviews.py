"""Pull requests: reviewer selection, reviews pinned to a commit, findings, merge verification."""

from sqlalchemy import select

from . import tasks as T
from .core import Org, OrgError
from .models import Agent, AgentStatus, Finding, PullRequest, Review, ReviewAssignment, Task
from .models import TaskStatus as S


def get_pr(org: Org, number: int) -> PullRequest:
    pr = org.session.get(PullRequest, number)
    if pr is None:
        raise OrgError("not_found", f"PR #{number} not tracked")
    return pr


def upsert_pr(org: Org, number: int, *, title: str, head_sha: str, author_id: str | None = None,
              task_id: str | None = None, changed_paths: list[str] | None = None, actor: str = "sync",
              **fields) -> PullRequest:
    """Create or refresh a PR from the provider. A new head SHA makes earlier approvals stale."""
    pr = org.session.get(PullRequest, number)
    tags = sorted(org.policy.tags_for_paths(changed_paths)) if changed_paths is not None else None
    if pr is None:
        pr = PullRequest(number=number, title=title, head_sha=head_sha, author_id=author_id, task_id=task_id,
                         opened_at=org.now(), head_updated_at=org.now(), risk_tags=tags or [], **fields)
        org.session.add(pr)
        org.session.flush()
        if task_id:
            task = T.get_task(org, task_id)
            if number not in task.prs:
                task.prs = [*task.prs, number]
        org.audit(actor, "pr_tracked", f"pr:{number}", head_sha=head_sha, author=author_id)
        return pr
    pr.title = title
    if author_id is not None:
        pr.author_id = author_id
    if tags is not None:
        pr.risk_tags = sorted(set(pr.risk_tags) | set(tags))
    for k, v in fields.items():
        setattr(pr, k, v)
    if head_sha != pr.head_sha:
        old = pr.head_sha
        pr.head_sha, pr.head_updated_at = head_sha, org.now()
        org.audit(actor, "pr_head_moved", f"pr:{number}", old=old, new=head_sha)
        _task_back_to_review(org, pr, actor)
    org.touch()
    return pr


def _task_back_to_review(org: Org, pr: PullRequest, actor: str) -> None:
    task = org.session.get(Task, pr.task_id) if pr.task_id else None
    if task and S(task.status) in (S.CHANGES_REQUESTED, S.APPROVED):
        T.transition(org, task, S.IN_REVIEW, actor, f"new head {pr.head_sha[:7]}; reviews start again")


# ---- reviewer selection -------------------------------------------------------------------


def required_slots(org: Org, pr: PullRequest) -> list[tuple[str, list[str]]]:
    """(reason, acceptable roles in preference order) for every review the PR needs."""
    author = org.session.get(Agent, pr.author_id) if pr.author_id else None
    author_role = author.role if author else "default"
    review = org.policy.review
    slots: list[tuple[str, list[str]]] = []
    if org.policy.review_mode == "all_roles":
        for role in review["all_roles"]["roles"]:
            for agent in _active(org, [role]):
                if agent.id != pr.author_id:
                    slots.append((f"all_roles:{agent.id}", [f"@{agent.id}"]))
    else:
        table = review["seniority"]
        for roles in table.get(author_role, table["default"]):
            slots.append((f"seniority:{author_role}", list(roles)))
    for tag in pr.risk_tags:
        for roles in review["tags"].get(tag, []):
            slots.append((f"risk:{tag}", list(roles)))
    return slots


def _active(org: Org, roles: list[str]) -> list[Agent]:
    return list(org.session.scalars(
        select(Agent).where(Agent.role.in_(roles), Agent.status == AgentStatus.active).order_by(Agent.id)
    ))


def _review_load(org: Org, agent_id: str) -> int:
    rows = org.session.execute(
        select(ReviewAssignment.id).join(PullRequest, PullRequest.number == ReviewAssignment.pr_number)
        .where(ReviewAssignment.reviewer_id == agent_id, ReviewAssignment.active, PullRequest.state == "open")
    ).all()
    return len(rows)


def assign_reviewers(org: Org, pr: PullRequest, actor: str = "orgos") -> dict:
    """Fill every required slot with an independent reviewer. Idempotent: existing assignees fill slots first.

    Returns {"assigned": [...new agent ids], "unfilled": [(reason, roles)]}.
    """
    current = {a.reviewer_id for a in _assignments(org, pr)}
    taken: set[str] = set()
    assigned, unfilled = [], []
    for reason, roles in required_slots(org, pr):
        pick = _fill(org, pr, roles, current, taken)
        if pick is None:
            unfilled.append((reason, roles))
            continue
        taken.add(pick.id)
        if pick.id not in current:
            existing = org.session.scalar(select(ReviewAssignment).where(
                ReviewAssignment.pr_number == pr.number, ReviewAssignment.reviewer_id == pick.id))
            if existing:
                existing.active = True
            else:
                org.session.add(ReviewAssignment(pr_number=pr.number, reviewer_id=pick.id, reason=reason,
                                                 requested_at=org.now()))
            current.add(pick.id)
            assigned.append(pick.id)
            org.message("REVIEW_REQUEST", actor, pick.id, f"Review PR #{pr.number} at {pr.head_sha[:7]} ({reason})",
                        pr_number=pr.number, task_id=pr.task_id)
    if assigned:
        org.audit(actor, "reviewers_assigned", f"pr:{pr.number}", reviewers=assigned, mode=org.policy.review_mode)
    org.session.flush()
    return {"assigned": assigned, "unfilled": unfilled}


def _fill(org: Org, pr: PullRequest, roles: list[str], current: set[str], taken: set[str]) -> Agent | None:
    for role in roles:
        if role.startswith("@"):
            agent = org.session.get(Agent, role[1:])
            candidates = [agent] if agent and agent.status == AgentStatus.active else []
        else:
            candidates = _active(org, [role])
        candidates = [a for a in candidates if a.id != pr.author_id and a.id not in taken]
        if not candidates:
            continue
        already = [a for a in candidates if a.id in current]
        if already:
            return already[0]
        return min(candidates, key=lambda a: (_review_load(org, a.id), a.id))
    return None


def _assignments(org: Org, pr: PullRequest) -> list[ReviewAssignment]:
    return list(org.session.scalars(select(ReviewAssignment).where(
        ReviewAssignment.pr_number == pr.number, ReviewAssignment.active)))


# ---- reviews and findings -----------------------------------------------------------------


def record_review(org: Org, pr: PullRequest, reviewer_id: str, sha: str | None, verdict: str, *,
                  body: str = "", findings: list[tuple[bool, str]] = (), source_id: str | None = None) -> Review | None:
    """Record a formal decision. findings: (blocking, text). Returns None for a duplicate source_id."""
    if source_id and org.session.scalar(select(Review.id).where(Review.source_id == source_id)):
        return None
    if verdict not in ("approved", "changes_requested"):
        raise OrgError("bad_verdict", verdict)
    if reviewer_id == pr.author_id:
        raise OrgError("self_review", "the author cannot review their own PR")
    if not sha:
        raise OrgError("sha_required", "a review must name the commit it inspected")
    if sha != pr.head_sha and not pr.head_sha.startswith(sha) and not sha.startswith(pr.head_sha):
        raise OrgError("stale_sha", f"review of {sha[:7]} but head is {pr.head_sha[:7]}; review the current diff")
    reviewer = org.session.get(Agent, reviewer_id)
    if reviewer is None or reviewer.status != AgentStatus.active:
        raise OrgError("unknown_reviewer", reviewer_id)
    review = Review(pr_number=pr.number, reviewer_id=reviewer_id, sha=pr.head_sha, verdict=verdict, body=body,
                    source_id=source_id, at=org.now())
    org.session.add(review)
    org.session.flush()
    for blocking, text in findings:
        org.session.add(Finding(pr_number=pr.number, review_id=review.id, reviewer_id=reviewer_id,
                                blocking=blocking, body=text))
    reviewer.last_activity_at = org.now()
    org.audit(reviewer_id, f"review_{verdict}", f"pr:{pr.number}", sha=pr.head_sha,
              findings=len(findings), blocking=sum(1 for b, _ in findings if b))
    org.session.flush()
    if not send_back_if_needed(org, pr, reviewer_id):
        maybe_approve(org, pr, reviewer_id)
    return review


def maybe_approve(org: Org, pr: PullRequest, actor: str) -> bool:
    """Task -> APPROVED once every assigned reviewer approved the head and nothing blocking is open."""
    task = org.session.get(Task, pr.task_id) if pr.task_id else None
    if task is None or S(task.status) != S.IN_REVIEW:
        return False
    latest = latest_reviews(org, pr)
    assigned = {a.reviewer_id for a in _assignments(org, pr)}
    if not assigned or assign_reviewers_preview(org, pr)["unfilled"]:
        return False
    if any(rid not in latest or latest[rid].sha != pr.head_sha or latest[rid].verdict != "approved"
           for rid in assigned):
        return False
    if open_findings(org, pr, blocking_only=not org.policy.block_on_nonblocking):
        return False
    T.transition(org, task, S.APPROVED, actor, f"PR #{pr.number}: all required reviews approved")
    return True


def resolve_finding(org: Org, finding: Finding, actor: str, resolution: str, *, disposition: bool = False) -> None:
    """Resolve with a fix, or disposition (accept as-is). Only the reviewer who raised it or a merger may
    disposition a blocking finding; the author may only mark it fixed, and the reviewer re-reviews anyway."""
    if finding.status != "open":
        return
    agent = org.session.get(Agent, actor)
    if disposition and finding.blocking:
        if actor != finding.reviewer_id and (agent is None or agent.role not in org.policy.review["merger_roles"]):
            raise OrgError("not_authorized", "only the reviewer or the EM may disposition a blocking finding")
    finding.status = "dispositioned" if disposition else "resolved"
    finding.resolution, finding.resolved_by = resolution, actor
    org.audit(actor, "finding_" + finding.status, f"pr:{finding.pr_number}", finding=finding.id, note=resolution)


def open_findings(org: Org, pr: PullRequest, *, blocking_only: bool) -> list[Finding]:
    q = select(Finding).where(Finding.pr_number == pr.number, Finding.status == "open")
    if blocking_only:
        q = q.where(Finding.blocking)
    return list(org.session.scalars(q))


def latest_reviews(org: Org, pr: PullRequest) -> dict[str, Review]:
    latest: dict[str, Review] = {}
    for r in org.session.scalars(select(Review).where(Review.pr_number == pr.number).order_by(Review.at, Review.id)):
        latest[r.reviewer_id] = r
    return latest


def stale_approvals(org: Org, pr: PullRequest) -> list[str]:
    return [rid for rid, r in latest_reviews(org, pr).items() if r.verdict == "approved" and r.sha != pr.head_sha]


def send_back_if_needed(org: Org, pr: PullRequest, actor: str) -> bool:
    """Changes requested or open blocking findings send the task back to its author."""
    task = org.session.get(Task, pr.task_id) if pr.task_id else None
    blocking = open_findings(org, pr, blocking_only=not org.policy.block_on_nonblocking)
    current = [r for r in latest_reviews(org, pr).values() if r.sha == pr.head_sha]
    if not blocking and not any(r.verdict == "changes_requested" for r in current):
        return False
    if task and S(task.status) in (S.IN_REVIEW, S.APPROVED):
        T.transition(org, task, S.CHANGES_REQUESTED, actor, f"PR #{pr.number}: changes requested")
        if pr.author_id:
            org.message("REVIEW_FINDING", actor, pr.author_id,
                        f"PR #{pr.number} needs changes: {len(blocking)} unresolved finding(s)",
                        pr_number=pr.number, task_id=task.id)
    return True


# ---- merge --------------------------------------------------------------------------------


def merge_blockers(org: Org, pr: PullRequest) -> list[str]:
    """Every unmet merge condition, in plain words. Empty list = ready to merge."""
    out = []
    if pr.state != "open":
        out.append(f"PR is {pr.state}")
    if pr.draft:
        out.append("PR is a draft")
    if pr.ci_status != "success":
        out.append(f"CI is {pr.ci_status}")
    if pr.mergeable is False:
        out.append("merge conflict with base")
    elif pr.mergeable is None:
        out.append("mergeability unknown")
    if pr.author_id is None:
        out.append("no implementation owner")
    latest = latest_reviews(org, pr)
    assignments = {a.reviewer_id for a in _assignments(org, pr)}
    fill = assign_reviewers_preview(org, pr)
    if fill["unfilled"]:
        out.append("no eligible reviewer for: " + ", ".join(r for r, _ in fill["unfilled"]))
    for rid in sorted(assignments):
        r = latest.get(rid)
        if r is None:
            out.append(f"waiting on review from {rid}")
        elif r.sha != pr.head_sha:
            out.append(f"{rid}'s {r.verdict.replace('_', ' ')} is for {r.sha[:7]}, not head {pr.head_sha[:7]}")
        elif r.verdict != "approved":
            out.append(f"{rid} requested changes")
    if (n := len(open_findings(org, pr, blocking_only=True))):
        out.append(f"{n} unresolved blocking finding(s)")
    if org.policy.block_on_nonblocking:
        n = len(open_findings(org, pr, blocking_only=False)) - len(open_findings(org, pr, blocking_only=True))
        if n:
            out.append(f"{n} unresolved comment(s) (policy: every comment must be resolved)")
    if "gated" in pr.risk_tags and not pr.human_approval:
        out.append("needs the owner's explicit approval (approval-gated decision)")
    return out


def assign_reviewers_preview(org: Org, pr: PullRequest) -> dict:
    """What assign_reviewers would leave unfilled, without writing anything."""
    current = {a.reviewer_id for a in _assignments(org, pr)}
    taken: set[str] = set()
    unfilled = []
    for reason, roles in required_slots(org, pr):
        pick = _fill(org, pr, roles, current, taken)
        if pick is None:
            unfilled.append((reason, roles))
        else:
            taken.add(pick.id)
    missing = taken - current
    return {"unfilled": unfilled, "missing": sorted(missing)}


def merge(org: Org, pr: PullRequest, merger_id: str) -> str:
    """The EM verifies and merges through the provider. Never bypasses an unmet condition."""
    merger = org.session.get(Agent, merger_id)
    if merger is None or merger.status != AgentStatus.active or merger.role not in org.policy.review["merger_roles"]:
        raise OrgError("not_authorized", f"{merger_id} may not merge")
    if merger_id == pr.author_id:
        raise OrgError("self_merge", "the author cannot verify their own PR")
    preview = assign_reviewers_preview(org, pr)
    if preview["missing"]:
        raise OrgError("reviewers_missing", f"required reviewers not assigned: {', '.join(preview['missing'])}")
    blockers = merge_blockers(org, pr)
    if blockers:
        raise OrgError("not_ready", "; ".join(blockers))
    if org.provider is None:
        raise OrgError("no_provider", "no git provider configured; nothing was merged")
    approvers = sorted(rid for rid, r in latest_reviews(org, pr).items() if r.sha == pr.head_sha)
    note = f"MERGING: verified reviews from {', '.join(approvers)}, CI green on {pr.head_sha}"
    merge_sha = org.provider.merge(pr.number, pr.head_sha, note)
    pr.state, pr.merge_sha, pr.merged_at = "merged", merge_sha, org.now()
    pr.simulated = bool(getattr(org.provider, "simulated", False))
    org.audit(merger_id, "pr_merged", f"pr:{pr.number}", head_sha=pr.head_sha, merge_sha=merge_sha,
              simulated=pr.simulated, approvers=approvers)
    task = org.session.get(Task, pr.task_id) if pr.task_id else None
    if task:
        T.add_evidence(org, task, "completion", f"PR #{pr.number} merged as {merge_sha}"
                       + (" (SIMULATED provider)" if pr.simulated else ""), merger_id)
        if S(task.status) == S.IN_REVIEW:
            T.transition(org, task, S.APPROVED, merger_id, "all required reviews approved")
        if S(task.status) == S.APPROVED and all(
                (p := org.session.get(PullRequest, n)) is not None and p.state == "merged" for n in task.prs):
            T.transition(org, task, S.DONE, merger_id, f"PR #{pr.number} merged")
    return merge_sha
