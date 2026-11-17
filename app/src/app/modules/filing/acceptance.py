"""Accepting a warning as shown (LLD-5 §6; R1-M8 slice 1). Insert-only, one row per instance, check code and subject; the
same acceptance twice is a no-op. Only a warning that the current build still shows can be accepted: a block never, and a
finding that has since changed (new `subject_fp`) is refused so a stale screen cannot accept rows it has not seen."""

import uuid

from sqlalchemy import text

from platform_common import audit
from platform_common.errors import Conflict, Invalid
from platform_common.ids import uuid7
from platform_common.uow import BusinessUoW

from .checks import Finding
from .gate import ACCEPTABLE
from .periods import ReturnInstance


def accepted_set(tx, instance_id: uuid.UUID) -> set[tuple[str, str]]:
    rows = tx.execute(
        text("select check_code, subject_fp from filing.check_acceptances where instance_id = :i"), {"i": instance_id}
    )
    return {(r.check_code, r.subject_fp) for r in rows}


def accept(
    uow: BusinessUoW,
    instance: ReturnInstance,
    findings: list[Finding],
    check_code: str,
    subject_fp: str | None,
    note: str,
) -> int:
    """Record an acceptance for one finding (`subject_fp` given) or for every current warning with that code. Returns how
    many were newly recorded."""
    mine = [f for f in findings if f.code == check_code]
    if subject_fp is not None:
        mine = [f for f in mine if f.subject_fp == subject_fp]
    if not mine:
        raise Conflict("finding_not_current", "That item has changed. Reload the return and look at it again.")
    if any(f.level != ACCEPTABLE for f in mine):
        raise Invalid("cannot_accept", "This can't be accepted. It has to be fixed.", field="check_code")
    note = note.strip()
    if not note:
        raise Invalid("note_required", "Say why you are accepting this.", field="note")
    new = 0
    for f in mine:
        inserted = uow.tx.execute(
            text(
                "insert into filing.check_acceptances (id, business_id, instance_id, check_code, subject_fp, note, accepted_by)"
                " values (:id, :b, :i, :c, :fp, :n, :u) on conflict (business_id, instance_id, check_code, subject_fp)"
                " do nothing returning id"
            ),
            {
                "id": uuid7(),
                "b": uow.principal.business_id,
                "i": instance.id,
                "c": f.code,
                "fp": f.subject_fp,
                "n": note,
                "u": uow.principal.user_id,
            },
        ).first()
        new += inserted is not None
    if new:
        audit.record(
            uow,
            "filing.accept_warning",
            "return_instance",
            instance.id,
            reason=note,
            data={"check_code": check_code, "count": new},
        )
    return new
