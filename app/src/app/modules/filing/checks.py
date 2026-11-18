"""Checks over a built return (LLD-5 §6, GF-5). Each check is a function `(tx, build) -> list[Finding]` in one
registry. In R1-M7 every finding is report-only: nothing here blocks, changes a value or stops a build, and the level
is what the export (R1-M8) will act on. Messages name the row (its file and row number) and what to look at; they never
carry a GSTIN or an amount beyond the figures the person is asked to compare.

What is not decided here: no tolerance is chosen for a tax difference (any difference is shown), and no rule about
where a note goes. Anything a CA has not answered carries `needs_ca_check`.
"""

import hashlib
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from app.modules.business.interface import check_gstin, fy_of, gstin_state, hsn_band_missing, hsn_min_digits
from platform_common.money import PAISE

from app.modules.refdata import RefdataMissing, provenance_on, state_name, uqc_codes, value_on

from .build import ReturnBuild
from .gstr1 import SupplyLine

# Refdata values a build rests on; C-16 names the ones no CA has confirmed.
RELIED_ON = (
    "gstr1.b2cl_threshold",
    "hsn.pattern",
    "hsn.min_digits_up_to_threshold",
    "hsn.min_digits_above_threshold",
    "invoice.number.max_length",
    "invoice.number.charset",
)


@dataclass(frozen=True)
class Finding:
    code: str
    level: str  # block | warn | info: what the export will do; M7 only reports
    message: str
    source_refs: tuple[str, ...]
    subject_fp: str  # changes when the rows it is about change, so an acceptance can tell (R1-M8)
    needs_ca_check: bool = False


def _fp(code: str, *parts: str) -> str:
    return hashlib.sha256("|".join((code, *parts)).encode()).hexdigest()


def _line_fp(code: str, ln: SupplyLine) -> str:
    """What an acceptance is tied to: the document and every figure and code on the line, so a corrected line under the
    same file name and row is a different subject and needs a new acceptance (Lead review of #163)."""
    return _fp(
        code, ln.source_ref, str(ln.source_id), ln.doc_number, str(ln.doc_date), ln.doc_kind, ln.supply_class,
        ln.pos_state_code, ln.gstin, ln.counterparty_gstin or "", str(ln.rate), ln.hsn or "", ln.uqc or "",
        str(ln.quantity), str(ln.taxable_value), str(ln.igst), str(ln.cgst), str(ln.sgst), str(ln.cess),
    )  # fmt: skip


def _per_line(code, level, lines, message, *, ca=False) -> list[Finding]:
    return [Finding(code, level, message(ln), (ln.source_ref,), _line_fp(code, ln), ca) for ln in lines]


def _unit(ln: SupplyLine) -> str:
    return f"{ln.doc_kind.replace('_', ' ')} {ln.doc_number}"


def c01_missing_hsn(tx: Session, b: ReturnBuild) -> list[Finding]:
    bad = [ln for ln in b.lines if not (ln.hsn or "").strip()]
    return _per_line("C-01", "block", bad, lambda ln: f"{_unit(ln)} ({ln.source_ref}): HSN is missing.")


def c02_customer_gstin(tx: Session, b: ReturnBuild) -> list[Finding]:
    bad = [ln for ln in b.lines if ln.counterparty_gstin and not check_gstin(ln.counterparty_gstin, own=False).ok]
    return _per_line("C-02", "block", bad,
                     lambda ln: f"{_unit(ln)} ({ln.source_ref}): the customer GSTIN is not a valid GSTIN.")


def c03_document_number(tx: Session, b: ReturnBuild) -> list[Finding]:
    on = b.instance.period_end
    longest, charset = int(value_on(tx, "invoice.number.max_length", on)), value_on(tx, "invoice.number.charset", on)
    bad = {ln.source_id: ln for ln in b.lines if len(ln.doc_number) > longest or not charset.match(ln.doc_number)}
    return _per_line("C-03", "block", bad.values(),
                     lambda ln: f"{_unit(ln)} ({ln.source_ref}): the number is longer than {longest} characters or "
                                "uses characters the invoice rule does not allow.", ca=True)


def c04_duplicate_number(tx: Session, b: ReturnBuild) -> list[Finding]:
    seen: dict[tuple, dict] = defaultdict(dict)
    for ln in b.lines:
        seen[(ln.gstin, ln.doc_kind, fy_of(ln.doc_date), ln.doc_number.strip().upper())][ln.source_id] = ln
    out = []
    for (_, kind, _, number), docs in seen.items():
        if len(docs) > 1:
            refs = tuple(sorted({d.source_ref for d in docs.values()}))
            out.append(Finding("C-04", "block", f"The {kind.replace('_', ' ')} number {number} is used by "
                               f"{len(docs)} documents in one financial year ({', '.join(refs)}).", refs,
                               _fp("C-04", kind, number, *sorted(str(i) for i in docs))))
    return out


def c05_place_of_supply(tx: Session, b: ReturnBuild) -> list[Finding]:
    bad = [ln for ln in b.lines if state_name(tx, ln.pos_state_code, ln.doc_date) is None]
    return _per_line("C-05", "block", bad,
                     lambda ln: f"{_unit(ln)} ({ln.source_ref}): the place of supply is not a known state code.")


def c18_unit_not_listed(tx: Session, b: ReturnBuild) -> list[Finding]:
    """A unit the portal's list does not have would be refused by the portal, and mapping it is a guess, so it blocks the
    export (R1-M8). A blank unit is read as 'NA', which is not in our list of the portal's units either."""
    known = uqc_codes(tx, b.instance.period_end)
    return _per_line("C-18", "block", [ln for ln in b.lines if ln.uqc not in known],
                     lambda ln: f"{_unit(ln)} ({ln.source_ref}): " + (
                         "there is no unit, and the portal's list needs one." if ln.uqc == "NA"
                         else "the unit is not on the portal's list."))  # fmt: skip


def c10_hsn_digits(tx: Session, b: ReturnBuild) -> list[Finding]:
    months = {(ln.doc_date.year, ln.doc_date.month): ln.doc_date for ln in b.lines}
    digits = {m: hsn_min_digits(tx, d) for m, d in months.items()}
    band = any(hsn_band_missing(tx, d) is not None for d in months.values())  # one answer for the whole build
    short = [ln for ln in b.lines if (ln.hsn or "").strip() and len(ln.hsn) < digits[(ln.doc_date.year, ln.doc_date.month)]]
    return _per_line("C-10", "block", short,
                     lambda ln: f"{_unit(ln)} ({ln.source_ref}): the HSN has fewer than "
                                f"{digits[(ln.doc_date.year, ln.doc_date.month)]} digits.", ca=band)


def c12_negative_b2cs(tx: Session, b: ReturnBuild) -> list[Finding]:
    if value_on(tx, "gstr1_offline.allow_negative_b2cs", b.instance.period_end):
        return []
    heads = ("taxable_value", "igst", "cgst", "sgst", "cess")
    return [
        Finding("C-12", "block", f"The B2CS row for place of supply {r.pos_state_code} at {r.rate}% is negative after "
                "credit notes. The offline tool may not accept it; check with your CA.", r.source_refs,
                _fp("C-12", r.pos_state_code, str(r.rate), *r.source_refs), True)
        for r in b.sections.b2cs if any(getattr(r.amounts, h) < 0 for h in heads)
    ]

_RELIED_ON_PLAIN = {
    "gstr1.b2cl_threshold": "the limit for large sales to consumers",
    "hsn.pattern": "the format of an HSN code",
    "hsn.min_digits_up_to_threshold": "how many HSN digits are required",
    "hsn.min_digits_above_threshold": "how many HSN digits are required",
    "invoice.number.max_length": "the rules for invoice numbers",
    "invoice.number.charset": "the rules for invoice numbers",
}


def c16_provisional_values(tx: Session, b: ReturnBuild) -> list[Finding]:
    unconfirmed = []
    for key in RELIED_ON:
        try:
            confirmed, _ = provenance_on(tx, key, b.instance.period_end)
        except RefdataMissing:
            confirmed = False
        if not confirmed:
            unconfirmed.append(key)
    if not unconfirmed:
        return []
    plain = list(dict.fromkeys(_RELIED_ON_PLAIN[k] for k in unconfirmed))
    return [Finding("C-16", "warn", "A CA has not confirmed these rules yet: " + ", ".join(plain) + ".", (),
                    _fp("C-16", *unconfirmed), True)]


# -- Checks added with the offline tool in mind (LLD-5 §6: C-13, C-17) ----------------------------------------


def c13_line_items(tx: Session, b: ReturnBuild) -> list[Finding]:
    """More data rows than one file may hold: the export is split into several files (§7), and the person is told to
    watch the tool's own size message. The limit is a provisional refdata value, so the finding is marked for the CA."""
    limit = int(value_on(tx, "gstr1.offline_tool.max_lines", b.instance.period_end))
    if b.line_items <= limit:
        return []
    return [Finding("C-13", "warn", f"This return has {b.line_items} rows and one file holds at most {limit}, so the "
                    "export will be made as several files. Upload them one after the other, and check the tool's message "
                    "about the 5 MB file size limit.", (), _fp("C-13", str(b.line_items), str(limit)), True)]


def _tool_tax(taxable: Decimal, rate: Decimal, parts: int) -> Decimal:
    """What the offline tool works out for one row and one tax head: taxable value x rate, then to the paisa, half up."""
    return (taxable * rate / Decimal(100) / Decimal(parts)).quantize(PAISE, rounding=ROUND_HALF_UP)


def c17_tool_recompute(tx: Session, b: ReturnBuild) -> list[Finding]:
    """The tool works tax out again for every invoice-and-rate row (taxable value x rate), where we keep the sum of the
    tax of the row's lines. They can differ by a paisa. GSTR-3B is filled from GSTR-1, so the person is shown both figures
    and told to edit the row in the tool; our figures stay as the invoices have them. No tolerance: any difference shows.
    Cess is not compared (the rule says nothing about it). Which figure the return should carry is a CA question (CA-2)."""
    s = b.sections
    out = []
    for table, rows in (("Table 4A (B2B)", s.b2b), ("Table 5 (B2CL)", s.b2cl), ("Table 7 (B2CS)", s.b2cs),
                        ("Table 9B (registered notes)", s.cdnr), ("Table 9B (unregistered notes)", s.cdnur)):  # fmt: skip
        for r in rows:
            a = r.amounts
            if a.cgst == 0 and a.sgst == 0:
                pairs = (("IGST", a.igst, _tool_tax(a.taxable_value, r.rate, 1)),)
            else:
                half = _tool_tax(a.taxable_value, r.rate, 2)
                pairs = (("CGST", a.cgst, half), ("SGST", a.sgst, half))
            off = [(head, ours, tool) for head, ours, tool in pairs if ours != tool]
            if not off:
                continue
            figures = "; ".join(f"{head}: your invoice has {ours}, the tool will work out {tool}" for head, ours, tool in off)
            ref = ", ".join(r.source_refs)
            out.append(Finding("C-17", "warn", f"{table}, {ref} at {r.rate}%: {figures}. The tool works tax out again "
                               "for each row, so edit this row's tax in the tool to match your invoice.", r.source_refs,
                               _fp("C-17", table, str(r.rate), str(a.taxable_value), str(a.igst), str(a.cgst), str(a.sgst),
                                   *r.source_refs), True))
    return out


# -- Invariants and the IFF cap (LLD-5 §6: C-07, C-09, C-11) ------------------------------------------------


def c07_b2b_without_hsn_summary(tx: Session, b: ReturnBuild) -> list[Finding]:
    """One builder makes both, so this should never fire; it is kept as the invariant the BRD list asks for."""
    if not b.sections.b2b or b.sections.hsn_b2b:
        return []
    return [Finding("C-07", "block", "Something is wrong on our side: this return has business-to-business invoices but "
                    "no HSN summary for them. Do not use this return. We have been told.", (),
                    _fp("C-07", b.instance.id.hex, b.fingerprint))]


def c09_reconciliation(tx: Session, b: ReturnBuild) -> list[Finding]:
    """The liability tables and the HSN summary must agree on every head (L5-7; a QRMP quarter adds its IFF builds, S6-2,
    which `build.gap` already does). A difference is our error, never the person's, so the words are the system-error ones
    the export gate uses."""
    if b.gap.is_zero():
        return []
    return [Finding("C-09", "block", "Something is wrong on our side: the sections and the HSN summary do not add up. "
                    "Do not use this return. We have been told.", (), _fp("C-09", b.instance.id.hex, b.fingerprint))]


def c11_iff_cap(tx: Session, b: ReturnBuild) -> list[Finding]:
    """An IFF month may carry B2B invoices up to a limit (CGST Rule 59(2)). Assignment already keeps within it (L5-3), so
    this is the second guard if the refdata value changed. Credit notes are not counted until the GST expert says how
    they are (the refdata note), so the sum is the B2B invoice rows only."""
    if b.instance.form != "IFF":
        return []
    cap = Decimal(value_on(tx, "iff.max_taxable_value", b.instance.period_end))
    taxable = sum((r.amounts.taxable_value for r in b.sections.b2b), Decimal())
    if taxable <= cap:
        return []
    refs = tuple(sorted({ref for r in b.sections.b2b for ref in r.source_refs}))
    return [Finding("C-11", "warn", f"The business-to-business invoices in this IFF come to {taxable} and the limit for one "
                    f"IFF month is {cap}. Move some of them to the quarterly return, and check with your CA.", refs,
                    _fp("C-11", str(taxable), str(cap), *refs), True)]


# -- Own-invoice and arithmetic findings (decision 6: report-only, no tolerance chosen) ---------------------


def a1_tax_arithmetic(tx: Session, b: ReturnBuild) -> list[Finding]:
    out = []
    for ln in b.lines:
        expected, tax = ln.taxable_value * ln.rate / Decimal(100), ln.igst + ln.cgst + ln.sgst
        if expected != tax:
            out += _per_line("A-01", "warn", [ln],
                             lambda ln: f"{_unit(ln)} ({ln.source_ref}): tax is {tax} but taxable value x rate gives "
                                        f"{expected} (difference {tax - expected}).", ca=True)
    return out


def a2_heads_vs_place_of_supply(tx: Session, b: ReturnBuild) -> list[Finding]:
    out = []
    for ln in b.lines:
        intra = ln.pos_state_code == gstin_state(ln.gstin)
        if (intra and ln.igst) or (not intra and (ln.cgst or ln.sgst)):
            out += _per_line("A-02", "warn", [ln],
                             lambda ln: f"{_unit(ln)} ({ln.source_ref}): the tax heads do not fit the place of "
                                        "supply (IGST for a supply within the seller's state, or CGST/SGST outside it).",
                             ca=True)
    return out


def a3_cgst_sgst_differ(tx: Session, b: ReturnBuild) -> list[Finding]:
    bad = [ln for ln in b.lines if ln.cgst != ln.sgst]
    return _per_line("A-03", "warn", bad,
                     lambda ln: f"{_unit(ln)} ({ln.source_ref}): CGST is {ln.cgst} but SGST is {ln.sgst}.", ca=True)


def a4_number_in_two_years(tx: Session, b: ReturnBuild) -> list[Finding]:
    years: dict[tuple, dict[str, SupplyLine]] = defaultdict(dict)
    for ln in b.lines:
        years[(ln.gstin, ln.doc_kind, ln.doc_number.strip().upper())][fy_of(ln.doc_date)] = ln
    out = []
    for (_, kind, number), by_fy in years.items():
        if len(by_fy) > 1:
            refs = tuple(sorted(ln.source_ref for ln in by_fy.values()))
            out.append(Finding("A-04", "info", f"The {kind.replace('_', ' ')} number {number} is used in more than "
                               f"one financial year ({', '.join(sorted(by_fy))}). Numbers restart each year, so this "
                               "is fine if the years differ.", refs, _fp("A-04", kind, number, *sorted(by_fy)), True))
    return out


CHECKS: tuple[Callable[[Session, ReturnBuild], list[Finding]], ...] = (
    c01_missing_hsn, c02_customer_gstin, c03_document_number, c04_duplicate_number, c05_place_of_supply,
    c07_b2b_without_hsn_summary, c09_reconciliation, c10_hsn_digits, c11_iff_cap, c12_negative_b2cs, c13_line_items,
    c16_provisional_values, c17_tool_recompute, c18_unit_not_listed,
    a1_tax_arithmetic, a2_heads_vs_place_of_supply, a3_cgst_sgst_differ, a4_number_in_two_years,
)  # fmt: skip


def run_checks(tx: Session, build: ReturnBuild) -> list[Finding]:
    """Every finding for this build, in registry order and then in row order. Read-only."""
    return [f for check in CHECKS for f in check(tx, build)]
