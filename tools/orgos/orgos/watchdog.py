"""PR watchdog: deterministic, idempotent checks over every open PR.

Each condition is keyed on (PR, kind, head SHA). The first time a condition is seen the
watchdog acts once (assign reviewers, message the owner); later ticks only update
last_seen. A condition still open after `escalate_after_hours` is escalated once. A new
push changes the key, so the cycle restarts for the new commit; conditions no longer seen
are marked resolved.
"""

from datetime import timedelta

from sqlalchemy import select

from . import reviews as R
from .core import Org
from .models import Agent, AgentStatus, PullRequest, WatchdogAction


def _em(org: Org) -> str:
    em = org.session.scalar(select(Agent.id).where(Agent.role.in_(org.policy.review["merger_roles"]),
                                                   Agent.status == AgentStatus.active))
    return em or "ceo"


def _conditions(org: Org, pr: PullRequest) -> list[tuple[str, str, str]]:
    """(kind, recipient, text) for every problem the PR has right now."""
    out = []
    owner = org.session.get(Agent, pr.author_id) if pr.author_id else None
    owner_ok = owner is not None and owner.status == AgentStatus.active
    if not owner_ok:
        out.append(("no_owner", _em(org), f"PR #{pr.number} has no active implementation owner"))
    assigned = R._assignments(org, pr)
    preview = R.assign_reviewers_preview(org, pr)
    if not assigned or preview["missing"]:
        out.append(("reviewers_missing", _em(org), f"PR #{pr.number} is missing required reviewers"))
    if preview["unfilled"]:
        out.append(("no_eligible_reviewer", "ceo",
                    f"PR #{pr.number}: nobody can fill {', '.join(r for r, _ in preview['unfilled'])}"))
    sla = timedelta(hours=org.policy.review["review_sla_hours"])
    latest = R.latest_reviews(org, pr)
    for a in assigned:
        r = latest.get(a.reviewer_id)
        waiting_since = max(a.requested_at, pr.head_updated_at)
        if (r is None or r.sha != pr.head_sha) and org.now() - waiting_since > sla and not pr.draft:
            out.append((f"review_overdue:{a.reviewer_id}", a.reviewer_id,
                        f"PR #{pr.number} has waited over {sla.total_seconds() / 3600:.0f}h for your review"))
    if (stale := R.stale_approvals(org, pr)):
        out.append(("stale_approvals", pr.author_id or _em(org),
                    f"PR #{pr.number}: approvals from {', '.join(stale)} predate {pr.head_sha[:7]}"))
    blocking = R.open_findings(org, pr, blocking_only=True)
    if blocking:
        out.append(("blocking_findings", pr.author_id or _em(org),
                    f"PR #{pr.number} has {len(blocking)} unresolved blocking finding(s)"))
    if pr.ci_status == "failure":
        out.append(("ci_failed", pr.author_id or _em(org), f"PR #{pr.number}: CI failed on {pr.head_sha[:7]}"))
    if pr.mergeable is False:
        out.append(("merge_conflict", pr.author_id or _em(org), f"PR #{pr.number} conflicts with its base"))
    if not R.merge_blockers(org, pr):
        out.append(("ready_to_merge", _em(org), f"PR #{pr.number} meets every merge condition; verify and merge"))
    return out


def run(org: Org) -> list[dict]:
    """One pass. Returns only the actions taken this pass (empty when nothing changed)."""
    taken = []
    escalate_after = timedelta(hours=org.policy.review["escalate_after_hours"])
    seen_keys = set()
    for pr in org.session.scalars(select(PullRequest).where(PullRequest.state == "open")).all():
        for kind, recipient, text in _conditions(org, pr):
            key = f"{pr.number}:{kind}:{pr.head_sha}"
            seen_keys.add(key)
            row = org.session.get(WatchdogAction, key)
            if row is None or row.resolved_at is not None:
                if row is None:
                    row = WatchdogAction(key=key, pr_number=pr.number, kind=kind, first_seen=org.now(),
                                         last_seen=org.now())
                    org.session.add(row)
                else:
                    row.resolved_at, row.first_seen, row.last_seen, row.seen_count = None, org.now(), org.now(), 1
                taken.append(_act(org, pr, kind, recipient, text))
                continue
            row.last_seen, row.seen_count = org.now(), row.seen_count + 1
            if (not row.escalated and kind != "ready_to_merge"
                    and org.now() - row.first_seen >= escalate_after):
                row.escalated = True
                to = "ceo" if kind in ("no_eligible_reviewer", "no_owner") else _em(org)
                org.message("ESCALATION", "watchdog", to, f"Unresolved for {escalate_after}: {text}",
                            pr_number=pr.number, task_id=pr.task_id)
                taken.append({"pr": pr.number, "kind": kind, "action": "escalated", "to": to})
    for row in org.session.scalars(select(WatchdogAction).where(WatchdogAction.resolved_at.is_(None))).all():
        if row.key not in seen_keys:
            row.resolved_at = org.now()
    if taken:
        org.touch()
    org.session.flush()
    return taken


def _act(org: Org, pr: PullRequest, kind: str, recipient: str, text: str) -> dict:
    if kind == "reviewers_missing":
        result = R.assign_reviewers(org, pr, actor="watchdog")
        return {"pr": pr.number, "kind": kind, "action": "assigned_reviewers", "assigned": result["assigned"]}
    if kind == "stale_approvals":
        # Re-request the reviewers whose approval no longer covers the head.
        for rid in R.stale_approvals(org, pr):
            org.message("REVIEW_REQUEST", "watchdog", rid, f"Re-review PR #{pr.number} at {pr.head_sha[:7]}",
                        pr_number=pr.number, task_id=pr.task_id)
    if kind == "blocking_findings":
        R.send_back_if_needed(org, pr, "watchdog")
    msg_type = {"ready_to_merge": "APPROVAL_REQUEST", "blocking_findings": "REVIEW_FINDING",
                "no_eligible_reviewer": "ESCALATION", "no_owner": "ESCALATION"}.get(kind, "BLOCKER_REPORT")
    if kind.startswith("review_overdue"):
        msg_type = "REVIEW_REQUEST"
    org.message(msg_type, "watchdog", recipient, text, pr_number=pr.number, task_id=pr.task_id)
    return {"pr": pr.number, "kind": kind, "action": "notified", "to": recipient}
