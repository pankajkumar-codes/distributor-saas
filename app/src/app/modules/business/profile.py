"""The business profile after creation: reading it, editing it, turnover bands,
marketplace channels and the GSTIN lock (LLD-1 §8.2, §8.3, L1-14).

Every function works in the caller's unit of work on the business bound in
app.tenant_id; row-level security scopes each statement to it. Writers take the unit of
work, not just its transaction, because they write the audit row.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from platform_common import audit
from platform_common.errors import Conflict, Invalid
from platform_common.uow import UnitOfWork

from .fiscal import fy_of, previous_fy
from .frequency import carry_frequency
from .registration import Address, Registration, blank_to_none, check_state, registration

MARKETPLACES = ("amazon", "flipkart", "meesho")


@dataclass(frozen=True)
class Profile:
    business_id: uuid.UUID
    legal_name: str | None
    trade_name: str | None
    registration_kind: str
    gstin: str | None
    enrolment_number: str | None
    state_code: str
    gstin_locked: bool
    address_line1: str | None
    address_line2: str | None
    city: str | None
    pin: str | None
    address_state_code: str | None
    einvoice_history: str | None
    marketplaces_answered_at: datetime | None


@dataclass(frozen=True)
class Readiness:
    ok: bool
    missing: list[str]


@dataclass(frozen=True)
class TurnoverBand:
    fy: str
    band: str
    declared_turnover: Decimal | None


@dataclass(frozen=True)
class Channels:
    amazon: bool
    flipkart: bool
    meesho: bool
    answered: bool


@dataclass(frozen=True)
class BusinessSetup:
    profile_complete: bool
    frequency_set: bool
    marketplaces_answered: bool


_PROFILE = text(
    "select business_id, legal_name, trade_name, registration_kind, gstin, enrolment_number, state_code,"
    " gstin_locked_at is not null as gstin_locked, address_line1, address_line2, city, pin, address_state_code,"
    " einvoice_history, marketplaces_answered_at from business.profiles"
    " where business_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
)


def get_profile(tx: Session, *, for_update: bool = False) -> Profile | None:
    """The bound business's profile; None if it has none (a business from before S1)."""
    row = tx.execute(text(_PROFILE.text + (" for update" if for_update else ""))).one_or_none()
    return None if row is None else Profile(**row._mapping)


def ready_for_documents(tx: Session) -> Readiness:
    """What the first PDF or export still needs (LLD-1 §8.3, ON-3)."""
    p = get_profile(tx)
    if p is None:
        return Readiness(False, ["legal_name", "address", "gstin"])
    missing = []
    if p.legal_name is None:
        missing.append("legal_name")
    if None in (p.address_line1, p.city, p.pin, p.address_state_code):
        missing.append("address")
    if p.gstin is None:
        missing.append("gstin")  # an enrolment number doesn't make documents in R1 (LLD-1 §15)
    return Readiness(not missing, missing)


class ProfilePatch(BaseModel):
    """PATCH /profile: only the fields sent change. `registration` replaces the whole
    registration; `address` changes only the address fields sent."""

    model_config = ConfigDict(extra="forbid")

    registration: Registration | None = None
    legal_name: str | None = Field(default=None, max_length=200)
    trade_name: str | None = Field(default=None, max_length=200)
    address: Address | None = None
    einvoice_history: Literal["no", "yes", "not_sure"] | None = None


_UPDATE = text(
    "update business.profiles set legal_name = :legal_name, trade_name = :trade_name,"
    " registration_kind = :registration_kind, gstin = :gstin, enrolment_number = :enrolment_number,"
    " state_code = :state_code, address_line1 = :address_line1, address_line2 = :address_line2, city = :city,"
    " pin = :pin, address_state_code = :address_state_code, einvoice_history = :einvoice_history,"
    " updated_at = now(), updated_by = :by where business_id = :b"
)
_ADDRESS = {"line1": "address_line1", "line2": "address_line2", "city": "city", "pin": "pin",
            "state_code": "address_state_code"}


def update_profile(uow: UnitOfWork, patch: ProfilePatch, *, today: date) -> list[str]:
    """Apply PATCH /profile and return its warnings (LLD-1 §8.2). A registration change
    after the lock is 409 gstin_locked; before it, a new GSTIN keeps the old one's
    filing frequency (RM41-7)."""
    tx = uow.tx
    p = get_profile(tx, for_update=True)
    if p is None:
        raise Conflict("profile_missing", "This business has no profile yet")
    sent = patch.model_fields_set
    new = {k: v for k, v in p.__dict__.items() if k not in ("business_id", "gstin_locked", "marketplaces_answered_at")}
    warnings: list[str] = []

    if "registration" in sent:
        if patch.registration is None:
            raise Invalid("registration_required", "a business needs a GSTIN or an enrolment number",
                          field="registration")
        gstin, enrolment, state, reg_warnings = registration(tx, patch.registration, today)
        if (patch.registration.kind, gstin, enrolment, state) != (p.registration_kind, p.gstin,
                                                                   p.enrolment_number, p.state_code):
            if p.gstin_locked:
                raise Conflict("gstin_locked", "The GSTIN can't change after the first invoice is finalized")
            new.update(registration_kind=patch.registration.kind, gstin=gstin, enrolment_number=enrolment,
                       state_code=state)
        warnings += reg_warnings
    for name in ("legal_name", "trade_name"):
        if name in sent:
            new[name] = blank_to_none(getattr(patch, name))
    if "einvoice_history" in sent:
        new["einvoice_history"] = patch.einvoice_history
    if "address" in sent:
        # null clears the whole address; an object changes only the fields it carries.
        fields = _ADDRESS if patch.address is None else patch.address.model_fields_set
        for field in fields:
            value = None if patch.address is None else getattr(patch.address, field)
            new[_ADDRESS[field]] = value if field in ("pin", "state_code") else blank_to_none(value)
        if new["address_state_code"] is not None and new["address_state_code"] != p.address_state_code:
            check_state(tx, new["address_state_code"], today, "address.state_code")
    if new["address_state_code"] is not None and new["address_state_code"] != new["state_code"]:
        warnings.append("address_state_mismatch")  # a warning, not a refusal (L1-12)

    changed = sorted(k for k, v in new.items() if getattr(p, k) != v)
    if not changed:
        return warnings
    tx.execute(_UPDATE, {**new, "by": uow.principal.user_id, "b": p.business_id})
    audit.record(uow, "business.profile_update", "business", p.business_id, data={"fields": changed})
    if p.gstin is not None and new["gstin"] is not None and new["gstin"] != p.gstin:
        if carry_frequency(uow, p.gstin, new["gstin"]):
            warnings.append("frequency_carried")
    return warnings


def lock_gstin(uow: UnitOfWork) -> None:
    """L1-14: sales calls this in every live finalize (LLD-4 [S-4]). The first call locks
    the registration and writes the audit row; later calls do nothing."""
    locked = uow.tx.execute(
        text("update business.profiles set gstin_locked_at = now()"
             " where business_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
             " and gstin_locked_at is null returning business_id")
    ).scalar()
    if locked is not None:
        audit.record(uow, "business.gstin_locked", "business", locked)


# --- Turnover bands -------------------------------------------------------------------

_BAND = text("select fy, band, declared_turnover from business.turnover_bands where fy = :fy")


def turnover_band(tx: Session, fy: str) -> TurnoverBand | None:
    row = tx.execute(_BAND, {"fy": fy}).one_or_none()
    return None if row is None else TurnoverBand(row.fy, row.band, row.declared_turnover)


def set_turnover_band(uow: UnitOfWork, fy: str, band: str, declared_turnover: Decimal | None, *,
                      today: date) -> TurnoverBand:
    """PUT /turnover-bands/{fy}: the current FY or the one before (LLD-1 §8.2)."""
    current = fy_of(today)
    if fy not in (current, previous_fy(current)):
        raise Invalid("fy_not_allowed", f"set the band for {current} or {previous_fy(current)}", field="fy")
    uow.tx.execute(
        text("insert into business.turnover_bands (business_id, fy, band, declared_turnover, set_by)"
             " values (:b, :fy, :band, :turnover, :by)"
             " on conflict (business_id, fy) do update set band = excluded.band,"
             " declared_turnover = excluded.declared_turnover, set_at = now(), set_by = excluded.set_by"),
        {"b": uow.principal.business_id, "fy": fy, "band": band, "turnover": declared_turnover,
         "by": uow.principal.user_id},
    )
    audit.record(uow, "business.turnover_band_set", "business", uow.principal.business_id,
                 data={"fy": fy, "band": band})
    return TurnoverBand(fy, band, declared_turnover)


# --- Marketplace channels (ON-2) ----------------------------------------------------

def channels(tx: Session) -> Channels:
    """Which marketplaces the business sells on, and whether it has answered. A
    marketplace never answered is off. Answering never touches any data (ON-2)."""
    enabled = dict(tx.execute(text("select marketplace, enabled from business.marketplace_channels")).all())
    answered = tx.execute(
        text("select marketplaces_answered_at is not null from business.profiles"
             " where business_id = nullif(current_setting('app.tenant_id', true), '')::uuid")
    ).scalar()
    return Channels(*(enabled.get(m, False) for m in MARKETPLACES), answered=bool(answered))


def set_channels(uow: UnitOfWork, choice: dict[str, bool]) -> Channels:
    tx, p = uow.tx, uow.principal
    for marketplace in MARKETPLACES:
        tx.execute(
            text("insert into business.marketplace_channels (business_id, marketplace, enabled, changed_by)"
                 " values (:b, :m, :e, :by) on conflict (business_id, marketplace) do update"
                 " set enabled = excluded.enabled, changed_at = now(), changed_by = excluded.changed_by"
                 " where business.marketplace_channels.enabled is distinct from excluded.enabled"),
            {"b": p.business_id, "m": marketplace, "e": choice[marketplace], "by": p.user_id},
        )
    tx.execute(text("update business.profiles set marketplaces_answered_at = now() where business_id = :b"),
               {"b": p.business_id})
    audit.record(uow, "business.channels_update", "business", p.business_id,
                 data={"enabled": [m for m in MARKETPLACES if choice[m]]})
    return channels(tx)


def setup_state(tx: Session) -> BusinessSetup:
    """The business's part of the Home setup checklist (LLD-1 §10)."""
    p = get_profile(tx)
    frequency_set = p is not None and p.gstin is not None and bool(tx.execute(
        text("select exists (select 1 from business.filing_frequency_history where gstin = :g)"), {"g": p.gstin}
    ).scalar())
    return BusinessSetup(
        profile_complete=ready_for_documents(tx).ok,
        frequency_set=frequency_set,
        marketplaces_answered=p is not None and p.marketplaces_answered_at is not None,
    )
