"""Writes the four small GSTR-1 JSON files for the one test upload to the GST portal (R1-M8; team/research/r1-m8-test-upload-plan.md).

    python scripts/make_portal_test_files.py --gstin <the seller's GSTIN> --period MMYYYY --out <folder>

T1  one B2B invoice and one B2CS row, `chksum` omitted, system flags as in the tool's own file
T2  the same with a placeholder (wrong) `chksum`: tells whether the portal checks it
T3  the same as T1 with the system flags removed
T4  the whole builder output for the same invoices (B2B, B2CS and the HSN tables; Table 13 and Table 14 are not written)

The invoices are synthetic and numbered TEST/0001 so they cannot collide with a real invoice. Nothing is read from the
database and nothing is uploaded: a person uploads the file, never presses Submit, and removes the test records afterwards.
"""

import argparse
import re
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

from app.modules.filing import render_json as rj
from app.modules.filing.build import ReturnBuild
from app.modules.filing.export_model import export_model
from app.modules.filing.gstr1 import Amounts, SupplyLine, build_sections
from app.modules.filing.periods import ReturnInstance

BUYER = "27AAAAA0000A1Z5"  # a made-up registered buyer; the portal may mark it unknown, which is itself a result to note
D = Decimal


def _line(number: str, gstin: str, day: date, cls: str, pos: str, taxable: str, tax: str, value: str, buyer=None):
    half = D(tax) / 2
    intra = pos == gstin[:2]
    return SupplyLine(
        "own_invoice", uuid.uuid5(uuid.NAMESPACE_URL, number), number, gstin, day, number, "invoice", cls, pos,
        D("18"), "6109", "NOS", D("1"), D(taxable), D() if intra else D(tax), half if intra else D(),
        half if intra else D(), D(), D(value), counterparty_gstin=buyer,
    )  # fmt: skip


def lines_for(gstin: str, period: str) -> list[SupplyLine]:
    month, year = int(period[:2]), int(period[2:])
    day = date(year, month, 5)
    return [
        _line("TEST/0001", gstin, day, "B2B", "27", "1000.00", "180.00", "1180.00", BUYER),
        _line("TEST/0002", gstin, day, "B2CS", gstin[:2], "500.00", "90.00", "590.00"),
    ]


def model_for(gstin: str, period: str):
    month, year = int(period[:2]), int(period[2:])
    first = date(year, month, 1)
    last = date(year + month // 12, month % 12 + 1, 1)
    end = date.fromordinal(last.toordinal() - 1)
    inst = ReturnInstance(uuid.uuid5(uuid.NAMESPACE_URL, "portal-test"), gstin, "GSTR1", f"{year}-{month:02d}", first, end, None, "open")
    lines = lines_for(gstin, period)
    s = build_sections(lines, kind="GSTR1")
    build = ReturnBuild(instance=inst, sections=s, liability=Amounts(), hsn_total=Amounts(), gap=Amounts(), members=(),
                        line_items=s.line_items, fingerprint="0" * 64, refdata_as_of={}, ca_flags=(), debit_notes=0,
                        draft=True, lines=tuple(lines))  # fmt: skip
    return export_model(build)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gstin", required=True)
    ap.add_argument("--period", required=True, help="MMYYYY of an open, unfiled period")
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args()
    if not re.fullmatch(r"[0-9]{2}[A-Z0-9]{13}", a.gstin) or not re.fullmatch(r"(0[1-9]|1[0-2])[0-9]{4}", a.period):
        raise SystemExit("gstin must be 15 characters and period MMYYYY")
    a.out.mkdir(parents=True, exist_ok=True)
    full = model_for(a.gstin, a.period)
    small = type(full)(full.gstin, full.period, b2b=full.b2b, b2cs=full.b2cs)  # no HSN in T1 to T3 (plan section 3)
    files = {
        "T1_chksum_omitted": rj.render_json(small),
        "T2_chksum_placeholder": rj.render_json(small, rj.Options(chksum="placeholder")),
        "T3_flags_removed": rj.render_json(small, rj.Options(flags=False)),
        "T4_full_builder_output": rj.render_json(full),
    }
    for name, data in files.items():
        (a.out / f"{name}.json").write_bytes(data)
        print(f"{name}.json  {len(data)} bytes")


if __name__ == "__main__":
    main()
