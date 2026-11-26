"""build_return: the one place that sums a return's supply lines (LLD-5 §5, L5-1).

Reads `filing.v_supply_lines` (view contract v1) for the instance's member sets and hands them to the pure
section builder. Nothing here edits anything. The result carries a fingerprint (SHA-256 over the member lines
and the instance) and the list of things this build rests on that a CA has not
answered yet, so every screen, check and export shows the same list.

Member sets (LLD-5 §5):
- a monthly GSTR-1 or an IFF: the lines assigned to it;
- a QRMP quarter's GSTR-1: its own lines plus the lines of skipped IFFs forwarded to it (liability tables),
  and its own lines plus every IFF month of the quarter for Table 12.
"""

import hashlib
import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.refdata import uqc_codes

from .gstr1 import Amounts, Gstr1Sections, SupplyLine, build_sections
from .gstr1.sections import PENDING_PLAIN, hsn_total, liability, reconciliation_gap
from .periods import BOUND, ReturnInstance, instances_between

_LINE_COLUMNS = (
    "source_kind, source_id, source_ref, gstin, doc_date, doc_number, doc_kind, supply_class, pos_state_code,"
    " rate, hsn, uqc, quantity, taxable_value, igst, cgst, sgst, cess, doc_value, counterparty_gstin,"
    " counterparty_name, return_instance_id, return_period, original_doc_number, original_doc_date"
)

# What every build of uploaded invoices rests on and the CA has not answered (OPEN_QUESTIONS). Shown with
# the return, never hidden. Codes are stable; the wording is for people.
M7_OMISSIONS = (
    ("marketplace_reports", "Amazon, Flipkart and Meesho reports are not in this return until the CA answers"
                            " how they are treated."),
    ("exports_sez_rcm", "Exports, SEZ supplies, reverse charge, advances, nil-rated and exempt supplies are"
                        " not built from uploads yet; confirm with your CA."),
    ("uqc_mapping", "Units come from your file as typed; the match to the portal's unit list needs a CA check."),
)


@dataclass(frozen=True)
class CaFlag:
    code: str
    text: str


@dataclass(frozen=True)
class ReturnBuild:
    instance: ReturnInstance
    sections: Gstr1Sections
    liability: Amounts
    hsn_total: Amounts
    gap: Amounts  # liability minus Table 12; zero when they agree (L5-7)
    members: tuple[str, ...]  # the documents in it, "doc_number|source_kind|source_id", sorted
    line_items: int
    fingerprint: str
    refdata_as_of: dict[str, str]
    ca_flags: tuple[CaFlag, ...]
    debit_notes: int  # debit notes confirmed before #462, dated in this period, that have no return (so not in it)
    draft: bool  # a return is a draft until it is marked filed and locked
    lines: tuple[SupplyLine, ...] = ()  # every member line (liability and Table 12), for the checks
    # Own live documents cancelled in this return's member sets (#456): out of Tables 4 to 12, counted in Table 13.
    cancelled: tuple["CancelledDoc", ...] = ()
    iff_sections: tuple[Gstr1Sections, ...] = ()  # a quarter's IFF months filed with the IFF; counted in `liability`


@dataclass(frozen=True)
class CancelledDoc:
    doc_kind: str
    doc_number: str


def _cancelled(tx: Session, instance: ReturnInstance, ids: list[uuid.UUID]) -> list[CancelledDoc]:
    rows = tx.execute(
        text(f"select doc_kind, doc_number from sales.v_cancelled_documents where {BOUND} and gstin = :g"
             " and return_instance_id = any(:ids) order by doc_number"),
        {"g": instance.gstin, "ids": ids},
    ).all()
    return [CancelledDoc(r.doc_kind, r.doc_number) for r in rows]


def build_return(tx: Session, instance: ReturnInstance) -> ReturnBuild:
    if instance.form not in ("GSTR1", "IFF"):
        raise ValueError(f"{instance.form} is not built from supply lines")
    quarter = _is_qrmp_quarter(tx, instance)
    own = [instance.id]
    iff_months: list[uuid.UUID] = []
    iff_filed: list[uuid.UUID] = []  # IFF months whose lines were filed with the IFF, not with the quarter
    if quarter:
        forwarded = _forwarded_iffs(tx, instance)
        own += forwarded
        for i in instances_between(tx, instance.gstin, instance.period_start, instance.period_end):
            if i.form == "IFF":
                iff_months.append(i.id)
                if i.id not in forwarded:
                    iff_filed.append(i.id)
    liability_lines = _lines(tx, instance, own)
    hsn_lines = _lines(tx, instance, own + iff_months) if quarter else None
    sections = build_sections(liability_lines, kind=instance.form, hsn_lines=hsn_lines)
    iff_builds = [build_sections(_lines(tx, instance, iff_filed), kind="IFF")] if iff_filed else []
    all_lines = liability_lines if hsn_lines is None else _union(liability_lines, hsn_lines)
    debit_notes = _debit_notes(tx, instance)  # an old debit note has no return, so count by the instance's own dates
    cancelled = _cancelled(tx, instance, own + iff_months if quarter else own)
    return ReturnBuild(
        instance=instance,
        sections=sections,
        liability=liability(sections, *iff_builds),
        hsn_total=hsn_total(sections),
        gap=reconciliation_gap(sections, iff_builds=iff_builds),
        members=tuple(sorted({f"{ln.doc_number}|{ln.source_kind}|{ln.source_id}" for ln in all_lines})),
        line_items=sections.line_items,
        fingerprint=_fingerprint(instance, all_lines, debit_notes, cancelled),
        refdata_as_of={},  # nothing is read from refdata here: classification used its dated thresholds at confirm
        ca_flags=_flags(tx, instance, all_lines, sections, debit_notes),
        debit_notes=debit_notes,
        draft=instance.status != "filed_locked",
        lines=tuple(all_lines),
        iff_sections=tuple(iff_builds),
        cancelled=tuple(cancelled),
    )


# -- Member sets --------------------------------------------------------------------------


def _is_qrmp_quarter(tx: Session, instance: ReturnInstance) -> bool:
    if instance.form != "GSTR1":
        return False
    r = tx.execute(
        text(f"select filer_frequency from filing.return_instances where {BOUND} and id = :id"),
        {"id": instance.id},
    ).one()
    return r.filer_frequency == "qrmp"


def _forwarded_iffs(tx: Session, instance: ReturnInstance) -> list[uuid.UUID]:
    """Skipped IFFs forwarded to this quarter: their lines are liability of the quarter (LLD-5 §4)."""
    rows = tx.execute(
        text(
            "select id from filing.return_instances where "
            f"{BOUND} and form = 'IFF' and status = 'skipped' and forwarded_to = :to"
        ),
        {"to": instance.id},
    )
    return [r.id for r in rows]


def _lines(tx: Session, instance: ReturnInstance, ids: list[uuid.UUID]) -> list[SupplyLine]:
    rows = tx.execute(
        text(
            f"select {_LINE_COLUMNS} from filing.v_supply_lines where {BOUND} and gstin = :g"
            " and return_instance_id = any(:ids)"
        ),
        {"g": instance.gstin, "ids": ids},
    ).all()
    return [SupplyLine(**r._mapping) for r in rows]


def _union(a: list[SupplyLine], b: list[SupplyLine]) -> list[SupplyLine]:
    seen, out = set(), []
    for ln in (*a, *b):
        if (k := _line_key(ln)) not in seen:
            seen.add(k)
            out.append(ln)
    return out


def _debit_notes(tx: Session, instance: ReturnInstance) -> int:
    return tx.execute(
        text(
            f"select count(*) from imports.v_unsummed_documents where {BOUND} and gstin = :g"
            " and doc_kind = 'debit_note' and doc_date between :s and :e"
        ),
        {"g": instance.gstin, "s": instance.period_start, "e": instance.period_end},
    ).scalar_one()


# -- What the build rests on --------------------------------------------------------------


def _flags(
    tx: Session, instance: ReturnInstance, lines: list[SupplyLine], sections: Gstr1Sections, debit_notes: int
) -> tuple[CaFlag, ...]:
    flags = [CaFlag(*PENDING_PLAIN[t]) for t in sections.pending]  # plain words; the team text stays in sections.py
    if debit_notes:
        flags.append(CaFlag("debit_notes_unsummed", f"{debit_notes} debit note(s) uploaded before debit notes were"
                                                    " supported are not in this return yet: needs CA check."))
    flags += [CaFlag(code, t) for code, t in M7_OMISSIONS]
    known = uqc_codes(tx, instance.period_end)
    unlisted = sorted({ln.uqc for ln in lines if ln.uqc not in known})
    if unlisted:
        flags.append(CaFlag("uqc_unlisted", "Units not on the portal's list: " + ", ".join(unlisted)))
    return tuple(flags)


# -- Fingerprint --------------------------------------------------------------------------


def _line_key(ln: SupplyLine) -> tuple:
    return (
        str(ln.source_id), ln.source_ref, ln.hsn, ln.uqc, str(ln.rate), str(ln.quantity), str(ln.taxable_value),
        str(ln.igst), str(ln.cgst), str(ln.sgst), str(ln.cess), str(ln.doc_value), ln.doc_kind, ln.supply_class,
        ln.doc_number, ln.doc_date.isoformat(), ln.pos_state_code, ln.counterparty_gstin or "",
        ln.original_doc_number or "", ln.original_doc_date.isoformat() if ln.original_doc_date else "",
    )  # fmt: skip


def _fingerprint(instance: ReturnInstance, lines: list[SupplyLine], debit_notes: int,
                 cancelled: list[CancelledDoc] = ()) -> str:
    h = hashlib.sha256()
    h.update(f"{instance.id}|{instance.form}|{instance.period}|{debit_notes}\n".encode())
    for k in sorted(_line_key(ln) for ln in lines):
        h.update("|".join(k).encode() + b"\n")
    for c in sorted((c.doc_kind, c.doc_number) for c in cancelled):  # a cancel changes Table 13, so the build too
        h.update(f"cancelled|{c[0]}|{c[1]}\n".encode())
    return h.hexdigest()
