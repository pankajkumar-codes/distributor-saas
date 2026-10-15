"""Bring external PR state in: GitHub-shaped PR snapshots, review comments, webhook deliveries.

Review comments follow team/engineering.md section 4 (the shared GitHub account cannot
approve its own PRs, so each role reviews in a comment):

    REVIEW: APPROVED by Lead Engineer            (or REVIEW: CHANGES REQUESTED by ...)
    Reviewed-SHA: d3d33b7                        (optional if the body names the commit in `backticks`)
    - **blocking** what must change              (or [blocking])
    - **nit** what could change                  (or [nit])
"""

import re

from sqlalchemy import select

from . import reviews as R
from .core import Org, OrgError
from .models import Agent, WebhookDelivery

HEADER = re.compile(r"^\s*REVIEW:\s*(APPROVED|CHANGES[ _]REQUESTED)\s+by\s+(.+?)\s*$", re.I | re.M)
SHA_LINE = re.compile(r"Reviewed-SHA:\s*`?([0-9a-f]{7,40})`?", re.I)
SHA_TICK = re.compile(r"`([0-9a-f]{7,40})`")
AUTHOR_LINE = re.compile(r"^\s*Author[- ]role:\s*(.+?)\s*$", re.I | re.M)
FINDING = re.compile(r"(\*\*(blocking|nit)\*\*|\[(blocking|nit)\])\s*:?\s*(.*)", re.I)


def _norm(label: str) -> str:
    label = re.sub(r"\bengineer\b", "", label.lower())
    return re.sub(r"[^a-z0-9]+", " ", label).strip()


def resolve_agent(org: Org, label: str) -> Agent | None:
    key = _norm(label)
    agents = list(org.session.scalars(select(Agent)))
    for a in agents:
        if key in (_norm(a.name), _norm(a.id)):
            return a
    if key in ("em", "manager"):
        return next((a for a in agents if a.role == "em"), None)
    return None


def parse_review_comment(body: str) -> dict | None:
    m = HEADER.search(body)
    if not m:
        return None
    sha = SHA_LINE.search(body) or SHA_TICK.search(body)
    findings = []
    for line in body.splitlines():
        f = FINDING.search(line)
        if f:
            kind = (f.group(2) or f.group(3)).lower()
            findings.append((kind == "blocking", f.group(4).strip() or line.strip()))
    verdict = "approved" if m.group(1).upper() == "APPROVED" else "changes_requested"
    return {"verdict": verdict, "reviewer": m.group(2).strip(), "sha": sha.group(1) if sha else None,
            "findings": findings}


def ci_from_check_runs(check_runs: list[dict]) -> str:
    if not check_runs:
        return "pending"
    if any(c.get("conclusion") in ("failure", "timed_out", "cancelled", "action_required") for c in check_runs):
        return "failure"
    if all(c.get("status") == "completed" and c.get("conclusion") in ("success", "skipped", "neutral")
           for c in check_runs):
        return "success"
    return "pending"


def ingest_pr(org: Org, pr: dict, *, comments: list[dict] = (), check_runs: list[dict] | None = None,
              files: list[str] | None = None, author: str | None = None, task_id: str | None = None,
              actor: str = "sync") -> dict:
    """Reconcile one PR from GitHub-shaped JSON. Safe to run repeatedly with the same input."""
    author_agent = None
    label = author or (m.group(1) if (m := AUTHOR_LINE.search(pr.get("body") or "")) else None)
    if label:
        author_agent = resolve_agent(org, label)
        if author_agent is None:
            raise OrgError("unknown_author", f"no agent matches {label!r}")
    state = "merged" if pr.get("merged") else pr.get("state", "open")
    fields = {"state": state, "draft": bool(pr.get("draft"))}
    if "mergeable" in pr:
        fields["mergeable"] = pr["mergeable"]
    elif pr.get("mergeable_state") in ("dirty",):
        fields["mergeable"] = False
    if check_runs is not None:
        fields["ci_status"] = ci_from_check_runs(check_runs)
    tracked = R.upsert_pr(org, pr["number"], title=pr["title"], head_sha=pr["head"]["sha"],
                          author_id=author_agent.id if author_agent else None, task_id=task_id,
                          changed_paths=files, actor=actor, **fields)
    report = {"pr": tracked.number, "reviews_recorded": [], "reviews_rejected": []}
    for c in comments:
        parsed = parse_review_comment(c.get("body") or "")
        if parsed is None:
            continue
        reviewer = resolve_agent(org, parsed["reviewer"])
        source = f"github-comment:{c['id']}"
        if reviewer is None:
            report["reviews_rejected"].append((source, f"unknown reviewer {parsed['reviewer']!r}"))
            continue
        try:
            rec = R.record_review(org, tracked, reviewer.id, parsed["sha"], parsed["verdict"], body=c["body"],
                                  findings=parsed["findings"], source_id=source)
        except OrgError as e:
            # Kept visible, never silently dropped: e.g. a review of an old commit.
            report["reviews_rejected"].append((source, e.code))
            continue
        if rec is not None:
            report["reviews_recorded"].append(reviewer.id)
    return report


def handle_webhook(org: Org, delivery_id: str, event: str, payload: dict) -> str:
    """GitHub may redeliver; each delivery id is processed once."""
    if org.session.get(WebhookDelivery, delivery_id) is not None:
        return "duplicate"
    org.session.add(WebhookDelivery(delivery_id=delivery_id, received_at=org.now()))
    if event == "pull_request":
        ingest_pr(org, payload["pull_request"])
    elif event == "issue_comment" and payload.get("issue", {}).get("pull_request"):
        number = payload["issue"]["number"]
        pr = org.session.get(R.PullRequest, number)
        if pr is None:
            return "untracked_pr"
        ingest_pr(org, {"number": number, "title": pr.title, "head": {"sha": pr.head_sha}, "state": pr.state,
                        "draft": pr.draft}, comments=[payload["comment"]])
    elif event == "check_suite":
        pass  # check runs come in through ingest_pr(check_runs=...)
    org.touch()
    return "processed"
