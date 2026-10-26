import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Index, String, UniqueConstraint, Uuid, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from platform_common.permissions import Role

SCHEMA = "identity"


def _now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


# Since the LLD-1 reshape identity uses the four Release 1 roles (owner, admin,
# billing, CA) and the platform permission matrix, like every other module.


class MembershipStatus(str, enum.Enum):
    active = "active"
    deactivated = "deactivated"


class User(Base):
    """One per person (ON-1). S1 sign-up creates the row; locally X-Debug-User does."""

    __tablename__ = "users"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    cognito_sub: Mapped[str] = mapped_column(String, unique=True)
    email: Mapped[str] = mapped_column(String, unique=True)
    name: Mapped[str | None] = mapped_column(String)
    is_support: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Business(Base):
    __tablename__ = "businesses"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # Legal name moves to business.profiles (LLD-1 §4); until then the API still writes it.
    name: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String, default="active")
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("business_id", "user_id"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    business_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.businesses.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.users.id"))
    # Unused by the R1 design and dropped later (LLD-1 §3.3); the stock-era member routes
    # still name members by it until LLD-2 rebuilds them.
    user_sub: Mapped[str | None] = mapped_column(String(128), index=True)
    role: Mapped[Role] = mapped_column(Enum(Role, native_enum=False, length=20))
    status: Mapped[MembershipStatus] = mapped_column(
        Enum(MembershipStatus, native_enum=False, length=20), default=MembershipStatus.active
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deactivated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey(f"{SCHEMA}.users.id"))
    deactivation_reason: Mapped[str | None] = mapped_column(String)
    # Filled when a member joins through an invitation; older rows have neither.
    email: Mapped[str | None] = mapped_column(String(254))
    display_name: Mapped[str | None] = mapped_column(String(200))


class AuditEvent(Base):
    """Append-only. Never store tokens, passwords or full request payloads here."""

    __tablename__ = "audit_events"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.businesses.id"), index=True)
    actor_sub: Mapped[str] = mapped_column(String(128))
    action: Mapped[str] = mapped_column(String(80))
    entity_type: Mapped[str] = mapped_column(String(80))
    entity_id: Mapped[str] = mapped_column(String(80))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


INVITATION_DAYS = 7


class InvitationStatus(str, enum.Enum):
    pending = "pending"
    accepted = "accepted"
    revoked = "revoked"


class Delivery(str, enum.Enum):
    pending = "pending"
    sent = "sent"
    failed = "failed"


class Invitation(Base):
    __tablename__ = "invitations"
    __table_args__ = (
        # Mirrors migrations/0005: at most one open invitation per email per tenant.
        Index(
            "invitations_one_open",
            "tenant_id",
            "email",
            unique=True,
            postgresql_where=text("status = 'pending'"),
            sqlite_where=text("status = 'pending'"),
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.businesses.id"))
    email: Mapped[str] = mapped_column(String(254))
    display_name: Mapped[str | None] = mapped_column(String(200))
    role: Mapped[Role] = mapped_column(Enum(Role, native_enum=False, length=20))
    status: Mapped[InvitationStatus] = mapped_column(
        Enum(InvitationStatus, native_enum=False, length=20), default=InvitationStatus.pending
    )
    invited_by: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    delivery: Mapped[Delivery] = mapped_column(
        Enum(Delivery, native_enum=False, length=20), default=Delivery.pending
    )
    accepted_by: Mapped[str | None] = mapped_column(String(128))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
