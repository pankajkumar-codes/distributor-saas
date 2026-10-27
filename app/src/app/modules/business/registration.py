"""The registration and address rules shared by creating and editing a profile
(LLD-1 §5.10, §8.2, gstin.md)."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.modules.refdata import state_name
from platform_common.errors import Invalid

from .gstin import check_gstin, message

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


def blank_to_none(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


def check_state(tx: Session, code: str, on: date, field: str) -> None:
    """A state code must be in refdata.state_codes, and 96 (other country) is only ever a
    place of supply (gstin.md §3). An unknown code is refused: the check never passes
    for want of data."""
    if state_name(tx, code, on) is None or code == "96":
        raise Invalid("state_code_unknown", "that isn't a GST state code", field=field)


def registration(tx: Session, reg: Registration, on: date) -> tuple[str | None, str | None, str, list[str]]:
    """(gstin, enrolment_number, state_code, warnings), or Invalid."""
    if reg.kind == "gstin":
        if reg.enrolment_number is not None:
            raise Invalid("registration_mixed", "send a GSTIN or an enrolment number, not both",
                          field="registration.enrolment_number")
        check = check_gstin(reg.gstin or "")
        if not check.ok:
            code = check.errors[0]
            raise Invalid(code, message(code, reg.gstin or ""), field="registration.gstin")
        check_state(tx, check.state_code, on, "registration.gstin")
        if reg.state_code is not None and reg.state_code != check.state_code:
            raise Invalid("state_code_mismatch", "the state comes from the GSTIN's first two digits",
                          field="registration.state_code")
        return check.normalised, None, check.state_code, list(check.warnings)
    if reg.gstin is not None:
        raise Invalid("registration_mixed", "send a GSTIN or an enrolment number, not both", field="registration.gstin")
    number = blank_to_none(reg.enrolment_number)
    if number is None:
        # No cited pattern yet (LLD-1 §15): non-empty is the only check.
        raise Invalid("enrolment_number_required", "enter the enrolment number", field="registration.enrolment_number")
    if reg.state_code is None:
        raise Invalid("state_code_required", "choose the state you are enrolled in", field="registration.state_code")
    check_state(tx, reg.state_code, on, "registration.state_code")
    return None, number, reg.state_code, []
