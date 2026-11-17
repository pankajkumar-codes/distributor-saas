"""When a return may be exported (LLD-5 §6 "Acceptance", §7; R1-M8 slice 1). Pure: it looks at a build, its findings and the
acceptances on record, and says whether an export may start and, if not, why in words for the person.

An export needs: the instance open (a locked return is re-downloaded, not rebuilt), no block finding, no unsummed debit
note (nothing says where one goes until a CA answers), the sections reconciling to the HSN summary (our own error if
not, never a user warning), and every warning accepted as it is now (same `subject_fp`). Information findings need
nothing. Nothing here changes data."""

from dataclasses import dataclass

from .build import ReturnBuild
from .checks import Finding
from .periods import ReturnInstance

ACCEPTABLE = "warn"  # only warnings can be accepted; a block never, information never needs it


@dataclass(frozen=True)
class Reason:
    code: str
    message: str


@dataclass(frozen=True)
class Gate:
    reasons: tuple[Reason, ...]
    to_accept: int  # warnings still needing an acceptance

    @property
    def ready(self) -> bool:
        return not self.reasons and not self.to_accept


def accepted_key(f: Finding) -> tuple[str, str]:
    return f.code, f.subject_fp


def export_gate(
    instance: ReturnInstance, build: ReturnBuild, findings: list[Finding], accepted: set[tuple[str, str]]
) -> Gate:
    reasons: list[Reason] = []
    if instance.status != "open":
        reasons.append(Reason("not_open", "This return is not open, so it cannot be exported again."))
    blocks = sum(1 for f in findings if f.level == "block")
    if blocks:
        reasons.append(Reason("blocks", f"{blocks} item{'s' if blocks != 1 else ''} to fix first."))
    if build.debit_notes:
        reasons.append(
            Reason(
                "debit_notes",
                f"{build.debit_notes} debit note{'s' if build.debit_notes != 1 else ''} not"
                " in this return yet. They need a CA answer before this return can be exported.",
            )
        )
    if not build.gap.is_zero():
        reasons.append(
            Reason(
                "reconciliation",
                "Something is wrong on our side: the sections and the HSN summary do not"
                " add up. Do not use this return. We have been told.",
            )
        )
    to_accept = sum(1 for f in findings if f.level == ACCEPTABLE and accepted_key(f) not in accepted)
    return Gate(tuple(reasons), to_accept)
