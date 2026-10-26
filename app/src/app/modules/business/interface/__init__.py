"""What business offers the rest of the app (LLD-1 §9).

Every function takes the caller's transaction (`uow.tx`) and never opens or commits one.
Tenant rows are reached under row-level security: the business is the one bound in
app.tenant_id, except business_card, which reads under app_ro through profile_card_ro.
"""

import uuid
from dataclasses import dataclass
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.modules.refdata import state_name
from platform_common.errors import Invalid

from ..fiscal import fy_of
from ..gstin import GstinCheck, check_gstin, message

__all__ = [
    "Address",
    "BusinessCard",
    "GstinCheck",
    "NewBusinessProfile",
    "Registration",
    "business_card",
    "check_gstin",
    "create_profile",
    "display_name",
]

STATE = r"^[0-9]{2}$"


class Registration(BaseModel):
    kind: Literal["gstin", "enrolment"]
    gstin: str | None = Field(default=None, max_length=40)
    enrolment_number: str | None = Field(default=None, max_length=40)
    state_code: str | None = Field(default=None, pattern=STATE)  # chosen by the user for an enrolment


class Address(BaseModel):
    line1: str | None = Field(default=None, max_length=200)
    line2: str | None = Field(default=None, max_length=200)
    city: str | None = Field(default=None, max_length=100)
    pin: str | None = Field(default=None, pattern=r"^[0-9]{6}$")
    state_code: str | None = Field(default=None, pattern=STATE)


class NewBusinessProfile(BaseModel):
    """The body of POST /api/v1/b (LLD-1 §5.10)."""

    registration: Registration
    legal_name: str | None = Field(default=None, max_length=200)
    trade_name: str | None = Field(default=None, max_length=200)
    address: Address | None = None
    turnover_band: Literal["up_to_threshold", "above_threshold"]
    einvoice_history: Literal["no", "yes", "not_sure"]


@dataclass(frozen=True)
class BusinessCard:
    business_id: uuid.UUID
    display_name: str  # trade name, else legal name, else the GSTIN or enrolment number
    gstin: str | None
    state_code: str


def _blank_to_none(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


def _check_state(tx: Session, code: str, on: date, field: str) -> None:
    """A state code must be in refdata.state_codes, and 96 (other country) is only ever a
    place of supply (gstin.md §3). An unknown code is refused: the check never passes
    for want of data."""
    if state_name(tx, code, on) is None or code == "96":
        raise Invalid("state_code_unknown", "that isn't a GST state code", field=field)


def _registration(tx: Session, reg: Registration, on: date) -> tuple[str | None, str | None, str, list[str]]:
    """(gstin, enrolment_number, state_code, warnings), or Invalid."""
    if reg.kind == "gstin":
        if reg.enrolment_number is not None:
            raise Invalid("registration_mixed", "send a GSTIN or an enrolment number, not both",
                          field="registration.enrolment_number")
        check = check_gstin(reg.gstin or "")
        if not check.ok:
            code = check.errors[0]
            raise Invalid(code, message(code, reg.gstin or ""), field="registration.gstin")
        _check_state(tx, check.state_code, on, "registration.gstin")
        if reg.state_code is not None and reg.state_code != check.state_code:
            raise Invalid("state_code_mismatch", "the state comes from the GSTIN's first two digits",
                          field="registration.state_code")
        return check.normalised, None, check.state_code, list(check.warnings)
    if reg.gstin is not None:
        raise Invalid("registration_mixed", "send a GSTIN or an enrolment number, not both", field="registration.gstin")
    number = _blank_to_none(reg.enrolment_number)
    if number is None:
        # No cited pattern yet (LLD-1 §15): non-empty is the only check.
        raise Invalid("enrolment_number_required", "enter the enrolment number", field="registration.enrolment_number")
    if reg.state_code is None:
        raise Invalid("state_code_required", "choose the state you are enrolled in", field="registration.state_code")
    _check_state(tx, reg.state_code, on, "registration.state_code")
    return None, number, reg.state_code, []


_INSERT_PROFILE = text(
    "insert into business.profiles (business_id, legal_name, trade_name, registration_kind, gstin,"
    " enrolment_number, state_code, address_line1, address_line2, city, pin, address_state_code,"
    " einvoice_history, updated_by)"
    " values (:b, :legal_name, :trade_name, :kind, :gstin, :enrolment_number, :state_code, :line1, :line2,"
    " :city, :pin, :address_state_code, :einvoice_history, :by)"
)
_INSERT_BAND = text(
    "insert into business.turnover_bands (business_id, fy, band, set_by) values (:b, :fy, :band, :by)"
)


def create_profile(tx: Session, business_id: uuid.UUID, profile_in: NewBusinessProfile, *,
                   by: uuid.UUID, today: date) -> list[str]:
    """The new business's profile and its current-FY turnover band, in the caller's
    transaction, with app.tenant_id already bound to `business_id`. Returns warning codes
    (pan_shape, gstin_not_z, address_state_mismatch); refuses with Invalid."""
    gstin, enrolment, state, warnings = _registration(tx, profile_in.registration, today)
    address = profile_in.address or Address()
    if address.state_code is not None:
        _check_state(tx, address.state_code, today, "address.state_code")
        if address.state_code != state:
            warnings.append("address_state_mismatch")  # a warning, not a refusal (L1-12)
    tx.execute(
        _INSERT_PROFILE,
        {
            "b": business_id,
            "legal_name": _blank_to_none(profile_in.legal_name),
            "trade_name": _blank_to_none(profile_in.trade_name),
            "kind": profile_in.registration.kind,
            "gstin": gstin,
            "enrolment_number": enrolment,
            "state_code": state,
            "line1": _blank_to_none(address.line1),
            "line2": _blank_to_none(address.line2),
            "city": _blank_to_none(address.city),
            "pin": address.pin,
            "address_state_code": address.state_code,
            "einvoice_history": profile_in.einvoice_history,
            "by": by,
        },
    )
    tx.execute(_INSERT_BAND, {"b": business_id, "fy": fy_of(today), "band": profile_in.turnover_band, "by": by})
    return warnings


_CARDS = text(
    "select business_id, coalesce(trade_name, legal_name, gstin, enrolment_number) as display_name,"
    " gstin, state_code from business.profiles where business_id in :ids"
).bindparams(bindparam("ids", expanding=True))


def business_card(tx: Session, business_ids: list[uuid.UUID]) -> list[BusinessCard]:
    """Name, GSTIN and state of each business the caller is an active member of, read
    under app_ro (profile_card_ro); others are simply absent. For /me and sign-in."""
    if not business_ids:
        return []
    return [
        BusinessCard(r.business_id, r.display_name, r.gstin, r.state_code)
        for r in tx.execute(_CARDS, {"ids": list(business_ids)})
    ]


def display_name(tx: Session) -> str | None:
    """The bound business's name as members see it (trade name, else legal name, else
    the GSTIN or enrolment number), read under the tenant policy. None if it has no
    profile. For invitation mails and previews, which snapshot it (LLD-2)."""
    return tx.execute(
        text("select coalesce(trade_name, legal_name, gstin, enrolment_number) from business.profiles"
             " where business_id = nullif(current_setting('app.tenant_id', true), '')::uuid")
    ).scalar()
