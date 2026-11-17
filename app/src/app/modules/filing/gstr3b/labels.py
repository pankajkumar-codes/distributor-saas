"""Row names of the GSTR-3B form as the official offline utility (V5.8, sheet `GSTR-3B`) prints them, for the screen and the
downloads. Text only: no tax numbers. They are re-checked against the live portal before launch (BRD GF-24; OPEN_QUESTIONS).

A row's `heads` are the columns the seller can type. `sgst_copies_cgst` mirrors the utility: central tax is typed once and the
state/UT column takes the same value, so unequal input is refused (GF-24).
"""

from dataclasses import dataclass

WORKSHEET_LABEL = "Worksheet, not a filing"
PORTAL_NOTE = "Numbers to check and enter on the GST portal."
OFFSET_NOTE = "Offset and payment are done on the GST portal."

HEAD_NAMES = {"igst": "Integrated Tax", "cgst": "Central Tax", "sgst": "State/UT Tax", "cess": "Cess"}


@dataclass(frozen=True)
class Row:
    key: str
    label: str
    heads: tuple[str, ...]  # columns the seller types; empty for rows we compute or leave to the portal
    sgst_copies_cgst: bool = False


TABLE_3_1 = (
    Row("a", "(a) Outward Taxable supplies (other than zero rated, nil rated and exempted)", ()),
    Row("b", "(b) Outward Taxable supplies (zero rated)", ()),
    Row("c", "(c) Other Outward Taxable supplies (Nil rated, exempted)", ()),
    Row("d", "(d) Inward supplies (liable to reverse charge)", ("taxable_value", "igst", "cgst", "sgst", "cess"), True),
    Row("e", "(e) Non-GST Outward supplies", ()),
)
TABLE_3_1_1_NOTE = "3.1.1 Supplies notified under section 9(5): check on the GST portal."

# Table 4 (Eligible ITC), as the utility lists it. Entered by the seller from GSTR-2B on the portal.
TABLE_4_AVAILABLE = (
    Row("import_goods", "(1) Import of goods", ("igst", "cess")),
    Row("import_services", "(2) Import of services", ("igst", "cess")),
    Row("rcm_inward", "(3) Inward supplies liable to reverse charge (other than 1 & 2 above)",
        ("igst", "cgst", "sgst", "cess"), True),
    Row("isd", "(4) Inward supplies from ISD", ("igst", "cgst", "sgst", "cess"), True),
    Row("other", "(5) All other ITC", ("igst", "cgst", "sgst", "cess"), True),
)  # fmt: skip
TABLE_4_REVERSED = (
    Row("rev_rules", "(1) As per rules 38, 42 & 43 of CGST Rules and section 17(5)", ("igst", "cgst", "sgst", "cess"), True),
    Row("rev_other", "(2) Others", ("igst", "cgst", "sgst", "cess")),
)
TABLE_4_OTHER = (
    Row("reclaimed", "(1) ITC reclaimed which was reversed under Table 4(B)(2) in earlier tax period",
        ("igst", "cgst", "sgst", "cess"), True),
    Row("ineligible", "(2) Ineligible ITC under section 16(4) & ITC restricted due to PoS rules",
        ("igst", "cgst", "sgst", "cess"), True),
)  # fmt: skip
NET_ITC_LABEL = "(C) Net ITC Available (A)-(B)"  # shown, available minus reversed; the app does not check any of it

# Table 5: exempt, nil-rated and non-GST inward supplies, by inter-state and intra-state.
TABLE_5 = (
    Row("composition_exempt_nil", "From a supplier under composition scheme, Exempt and Nil rated supply",
        ("inter", "intra")),
    Row("non_gst", "Non GST supply", ("inter", "intra")),
)  # fmt: skip
# Table 5.1: interest. The utility also lists late fee; the app shows it as information only and never calculates it.
TABLE_5_1 = (Row("interest", "Interest", ("igst", "cgst", "sgst", "cess")),)
