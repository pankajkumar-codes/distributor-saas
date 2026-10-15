"""Persisted state. Every table keeps history: nothing here is deleted to retire or close."""

import enum
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


def utcnow() -> datetime:
    return datetime.now(UTC)


class Money(TypeDecorator):
    """Exact decimal stored as text, so SQLite never rounds it through a float."""

    impl = String(40)
    cache_ok = True

    def process_bind_param(self, value, dialect):  # noqa: ARG002
        return None if value is None else str(Decimal(value))

    def process_result_value(self, value, dialect):  # noqa: ARG002
        return None if value is None else Decimal(value)


class UTCDateTime(TypeDecorator):
    """SQLite drops tzinfo; give every datetime back as UTC."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):  # noqa: ARG002
        if value is not None and value.tzinfo is None:
            raise ValueError("naive datetime")
        return value

    def process_result_value(self, value, dialect):  # noqa: ARG002
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value


class Base(DeclarativeBase):
    pass


class AgentStatus(enum.StrEnum):
    active = "active"
    suspended = "suspended"
    retired = "retired"


class TaskStatus(enum.StrEnum):
    BACKLOG = "BACKLOG"
    READY = "READY"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    BLOCKED = "BLOCKED"
    IN_REVIEW = "IN_REVIEW"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    APPROVED = "APPROVED"
    DONE = "DONE"
    CANCELLED = "CANCELLED"


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)  # e.g. "staff-2"
    name: Mapped[str] = mapped_column(String(80))
    role: Mapped[str] = mapped_column(String(40))
    department: Mapped[str] = mapped_column(String(40))
    seniority: Mapped[int] = mapped_column(Integer)
    capabilities: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default=AgentStatus.active)
    max_active_tasks: Mapped[int] = mapped_column(Integer, default=1)
    temporary: Mapped[bool] = mapped_column(Boolean, default=False)
    objective: Mapped[str | None] = mapped_column(Text)
    budget_usd: Mapped[Decimal | None] = mapped_column(Money)
    created_by: Mapped[str] = mapped_column(String(40), default="seed")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    retired_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_activity_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)  # board IDs, e.g. "T-003"
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    department: Mapped[str] = mapped_column(String(40), default="engineering")
    task_type: Mapped[str] = mapped_column(String(30), default="implementation")
    # 1 = critical incident/security ... 8 = exploratory (brief §5 order).
    priority: Mapped[int] = mapped_column(Integer, default=3)
    optional: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default=TaskStatus.BACKLOG)
    assignee_id: Mapped[str | None] = mapped_column(ForeignKey("agents.id"))
    creator: Mapped[str] = mapped_column(String(40))
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"))
    acceptance_criteria: Mapped[list] = mapped_column(JSON, default=list)
    required_capabilities: Mapped[list] = mapped_column(JSON, default=list)
    estimate_hours: Mapped[Decimal | None] = mapped_column(Money)
    actual_hours: Mapped[Decimal | None] = mapped_column(Money)
    blocker_reason: Mapped[str | None] = mapped_column(Text)
    prs: Mapped[list] = mapped_column(JSON, default=list)
    commits: Mapped[list] = mapped_column(JSON, default=list)
    test_evidence: Mapped[list] = mapped_column(JSON, default=list)
    completion_evidence: Mapped[list] = mapped_column(JSON, default=list)
    lease_owner: Mapped[str | None] = mapped_column(String(40))
    lease_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    ready_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class TaskDependency(Base):
    __tablename__ = "task_dependencies"

    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), primary_key=True)
    depends_on_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), primary_key=True)


class TaskEvent(Base):
    __tablename__ = "task_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    at: Mapped[datetime] = mapped_column(UTCDateTime)
    actor: Mapped[str] = mapped_column(String(40))
    from_status: Mapped[str | None] = mapped_column(String(20))
    to_status: Mapped[str] = mapped_column(String(20))
    note: Mapped[str] = mapped_column(Text, default="")


class PullRequest(Base):
    __tablename__ = "pull_requests"

    number: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    author_id: Mapped[str | None] = mapped_column(ForeignKey("agents.id"))
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"))
    head_sha: Mapped[str] = mapped_column(String(40))
    state: Mapped[str] = mapped_column(String(10), default="open")  # open | merged | closed
    draft: Mapped[bool] = mapped_column(Boolean, default=False)
    ci_status: Mapped[str] = mapped_column(String(10), default="pending")  # pending|success|failure
    mergeable: Mapped[bool | None] = mapped_column(Boolean)  # None = unknown
    risk_tags: Mapped[list] = mapped_column(JSON, default=list)
    human_approval: Mapped[str | None] = mapped_column(Text)  # link to the owner's approval
    merge_sha: Mapped[str | None] = mapped_column(String(40))
    simulated: Mapped[bool] = mapped_column(Boolean, default=False)
    opened_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    head_updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    merged_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class ReviewAssignment(Base):
    __tablename__ = "review_assignments"
    __table_args__ = (UniqueConstraint("pr_number", "reviewer_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pr_number: Mapped[int] = mapped_column(ForeignKey("pull_requests.number"), index=True)
    reviewer_id: Mapped[str] = mapped_column(ForeignKey("agents.id"))
    reason: Mapped[str] = mapped_column(String(200))
    requested_at: Mapped[datetime] = mapped_column(UTCDateTime)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Review(Base):
    """A formal decision on one commit. Comments without a verdict are Findings only."""

    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pr_number: Mapped[int] = mapped_column(ForeignKey("pull_requests.number"), index=True)
    reviewer_id: Mapped[str] = mapped_column(ForeignKey("agents.id"))
    sha: Mapped[str] = mapped_column(String(40))
    verdict: Mapped[str] = mapped_column(String(20))  # approved | changes_requested
    body: Mapped[str] = mapped_column(Text, default="")
    source_id: Mapped[str | None] = mapped_column(String(80), unique=True)  # e.g. GitHub comment id
    at: Mapped[datetime] = mapped_column(UTCDateTime)


class Finding(Base):
    __tablename__ = "findings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pr_number: Mapped[int] = mapped_column(ForeignKey("pull_requests.number"), index=True)
    review_id: Mapped[int | None] = mapped_column(ForeignKey("reviews.id"))
    reviewer_id: Mapped[str] = mapped_column(ForeignKey("agents.id"))
    blocking: Mapped[bool] = mapped_column(Boolean)
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open|resolved|dispositioned
    resolution: Mapped[str | None] = mapped_column(Text)
    resolved_by: Mapped[str | None] = mapped_column(String(40))


class Execution(Base):
    """One bounded agent run on one task."""

    __tablename__ = "executions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"), index=True)
    attempt: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20))  # running|succeeded|failed|timed_out|cancelled
    started_at: Mapped[datetime] = mapped_column(UTCDateTime)
    deadline_at: Mapped[datetime] = mapped_column(UTCDateTime)
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    budget_usd: Mapped[Decimal | None] = mapped_column(Money)
    max_tool_calls: Mapped[int | None] = mapped_column(Integer)
    tool_calls: Mapped[int] = mapped_column(Integer, default=0)
    # Usage is only ever what a provider reported. "unavailable" is a real, displayed state.
    usage_source: Mapped[str] = mapped_column(String(20), default="unavailable")
    cost_usd: Mapped[Decimal | None] = mapped_column(Money)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    model: Mapped[str | None] = mapped_column(String(60))
    result: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String(40))  # TASK_ASSIGNMENT, REVIEW_REQUEST, ESCALATION...
    sender: Mapped[str] = mapped_column(String(40))
    recipient: Mapped[str] = mapped_column(String(40))
    task_id: Mapped[str | None] = mapped_column(String(40))
    pr_number: Mapped[int | None] = mapped_column(Integer)
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open|answered|expired
    at: Mapped[datetime] = mapped_column(UTCDateTime)
    respond_by: Mapped[datetime | None] = mapped_column(UTCDateTime)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(UTCDateTime)
    actor: Mapped[str] = mapped_column(String(40))
    action: Mapped[str] = mapped_column(String(60))
    entity: Mapped[str] = mapped_column(String(80))
    details: Mapped[dict] = mapped_column(JSON, default=dict)


class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"

    delivery_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    received_at: Mapped[datetime] = mapped_column(UTCDateTime)


class WatchdogAction(Base):
    """One open condition per key. The key includes the head SHA, so a new push re-arms it."""

    __tablename__ = "watchdog_actions"

    key: Mapped[str] = mapped_column(String(160), primary_key=True)
    pr_number: Mapped[int] = mapped_column(Integer, index=True)
    kind: Mapped[str] = mapped_column(String(40))
    first_seen: Mapped[datetime] = mapped_column(UTCDateTime)
    last_seen: Mapped[datetime] = mapped_column(UTCDateTime)
    seen_count: Mapped[int] = mapped_column(Integer, default=1)
    escalated: Mapped[bool] = mapped_column(Boolean, default=False)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class StateVersion(Base):
    """Bumped on every write, so dashboards can poll cheaply and reconcile after reconnecting."""

    __tablename__ = "state_version"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
