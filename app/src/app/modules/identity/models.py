import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Index, String, UniqueConstraint, Uuid, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

SCHEMA = "identity"


def _now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Role(str, enum.Enum):
    """The six stock-era roles that identity's grandfathered check constraints still allow.

    LLD-1's reshape replaces them with platform_common.permissions.Role (owner, admin,
    billing, CA) and moves identity onto `require`. Until then they stay here, inside
    identity, so no other module can use them.
    """

    owner = "owner"
    admin = "admin"
    sales = "sales"
    inventory = "inventory"
    finance = "finance"
    viewer = "viewer"


# From the stock-era matrix: members.invite and audit.view were owner and admin.
MANAGE_MEMBERS = frozenset({Role.owner, Role.admin})
READ_AUDIT = frozenset({Role.owner, Role.admin})


class MembershipStatus(str, enum.Enum):
    active = "active"
    disabled = "disabled"


class Tenant(Base):
    __tablename__ = "tenants"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_sub"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.tenants.id"), index=True)
    user_sub: Mapped[str] = mapped_column(String(128), index=True)
    role: Mapped[Role] = mapped_column(Enum(Role, native_enum=False, length=20))
    status: Mapped[MembershipStatus] = mapped_column(
        Enum(MembershipStatus, native_enum=False, length=20), default=MembershipStatus.active
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    # Filled when a member joins through an invitation; older rows have neither.
    email: Mapped[str | None] = mapped_column(String(254))
    display_name: Mapped[str | None] = mapped_column(String(200))


class AuditEvent(Base):
    """Append-only. Never store tokens, passwords or full request payloads here."""

    __tablename__ = "audit_events"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.tenants.id"), index=True)
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
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.tenants.id"))
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
