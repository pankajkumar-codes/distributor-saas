import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from platform_common.ids import uuid7

SCHEMA = "imports"
# jsonb on PostgreSQL (the migration), plain JSON for the SQLite unit tests.
JSONType = JSON().with_variant(JSONB(), "postgresql")


def _now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class RunStatus(str, enum.Enum):
    staged = "staged"
    confirmed = "confirmed"
    discarded = "discarded"


class StagedRowStatus(str, enum.Enum):
    # Valid, and no confirmed earlier import has this record.
    new = "new"
    # A confirmed earlier import has this record with identical values.
    already_imported = "already_imported"
    # A confirmed earlier import has this record with different values (e.g. a status change).
    changed = "changed"
    duplicate = "duplicate"
    conflict = "conflict"
    invalid = "invalid"


class ImportRun(Base):
    __tablename__ = "import_runs"
    __table_args__ = (
        # Mirrors migrations/202610261000_imports_staging.sql: one live run per file and report type.
        Index(
            "import_runs_one_live_per_file",
            "business_id", "marketplace", "report_type", "checksum_sha256",
            unique=True,
            postgresql_where=text("status <> 'discarded'"),
            sqlite_where=text("status <> 'discarded'"),
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    business_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    marketplace: Mapped[str] = mapped_column(String(20))
    report_type: Mapped[str] = mapped_column(String(20))
    profile_id: Mapped[str] = mapped_column(String(120))
    profile_verified: Mapped[bool] = mapped_column(Boolean)
    filename: Mapped[str] = mapped_column(String(255))
    checksum_sha256: Mapped[str] = mapped_column(String(64))
    sheet: Mapped[str | None] = mapped_column(String(100))
    header_row_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[RunStatus] = mapped_column(
        Enum(RunStatus, native_enum=False, length=20), default=RunStatus.staged
    )
    summary: Mapped[dict] = mapped_column(JSONType, default=dict)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(Uuid)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ImportRow(Base):
    """Never updated after insert: it is the audit record of what the file said."""

    __tablename__ = "import_rows"
    __table_args__ = (UniqueConstraint("run_id", "row_number"), {"schema": SCHEMA})

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.import_runs.id"))
    business_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    row_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[StagedRowStatus] = mapped_column(Enum(StagedRowStatus, native_enum=False, length=20))
    raw: Mapped[dict] = mapped_column(JSONType)
    normalized: Mapped[dict | None] = mapped_column(JSONType)
    errors: Mapped[list] = mapped_column(JSONType, default=list)
    dedup_values: Mapped[list | None] = mapped_column(JSONType)
    dedup_key: Mapped[str | None] = mapped_column(String(64))
    content_hash: Mapped[str | None] = mapped_column(String(64))
