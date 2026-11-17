"""The GSTR-1 file as JSON for the GST portal's upload, from the export model (R1-M8 slice 3).

The layout follows one real file written by the Returns Offline Tool (research `gstr1-offline-json-structure.md`): top-level
keys, system flags, number style (a whole number is written without decimals, others with at most two, never an exponent,
never a float), empty tables left out, B2CS rows always with all four tax keys, B2B items and HSN rows with a tax key only when
it is not zero. Output is minified UTF-8 and the same model always gives the same bytes.

What is NOT verified against the portal, and what the test upload (T1 to T4) is for:
- `chksum` is left out. Whether the portal needs it is unknown (Options.chksum can write a placeholder for test T2).
- `gt` and `cur_gt` are 0, as in the sample. `fil_dt` is left out unless asked for.
- The sample holds no B2CL, CDNR or CDNUR table, so those follow the field names of the GSTN GSTR-1 schema with the same
  system flags as B2B. `unverified_tables` names them so a screen can say so.
- Tables 13 (documents issued) and 14 (tax collected by e-commerce operators) are not written: see `export_model.NOT_IN_FILE`.
- HSN rows carry no `desc`: we hold no official description text.
- A monthly return only: `filing_typ` is "M" and a quarterly or IFF file raises `NotRenderable` in the model.
"""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from platform_common.money import PAISE

from .export_model import ExportModel, HsnLine, Invoice, Item, Note

FILING_TYPE = "M"
PLACEHOLDER_CHKSUM = "0000000000000000000000000000000000000000000000000000000000000000"  # a wrong value, for test T2 only: never written by a real export
UNVERIFIED = ("b2cl", "cdnr", "cdnur")  # no sample of the tool's own JSON for these tables


@dataclass(frozen=True)
class Options:
    chksum: Literal["omit", "placeholder"] = "omit"
    flags: bool = True  # the system flags the tool writes (flag, cflag, cfs, updby); test T3 turns them off
    fil_dt: date | None = None
    gross_turnover: Decimal = Decimal()


def unverified_tables(model: ExportModel) -> tuple[str, ...]:
    return tuple(name for name in UNVERIFIED if getattr(model, name))


def render_json(model: ExportModel, options: Options = Options()) -> bytes:
    return dumps(_document(model, options)).encode("utf-8")


# -- the tree ---------------------------------------------------------------------------------------------------


def _document(m: ExportModel, o: Options) -> dict:
    doc: dict = {"gstin": m.gstin, "fp": m.period, "filing_typ": FILING_TYPE, "gt": o.gross_turnover,
                 "cur_gt": o.gross_turnover}  # fmt: skip
    if m.b2b:
        doc["b2b"] = [
            {**_flag(o, "cfs", "N"), "ctin": p.gstin, "inv": [_invoice(i, o, regular=True) for i in p.invoices]}
            for p in m.b2b
        ]
    if m.b2cl:
        doc["b2cl"] = [{"pos": g.pos, "inv": [_invoice(i, o) for i in g.invoices]} for g in m.b2cl]
    if m.b2cs:
        doc["b2cs"] = [_small(r, o) for r in m.b2cs]
    if m.cdnr:
        doc["cdnr"] = [
            {**_flag(o, "cfs", "N"), "ctin": p.gstin, "nt": [_note(n, o, registered=True) for n in p.notes]}
            for p in m.cdnr
        ]
    if m.cdnur:
        doc["cdnur"] = [_note(n, o, registered=False) for n in m.cdnur]
    if m.hsn_b2b or m.hsn_b2c:
        hsn: dict = {**_flag(o, "flag", "N")}
        if m.hsn_b2b:
            hsn["hsn_b2b"] = [_hsn(n, r) for n, r in enumerate(m.hsn_b2b, 1)]
        if m.hsn_b2c:
            hsn["hsn_b2c"] = [_hsn(n, r) for n, r in enumerate(m.hsn_b2c, 1)]
        doc["hsn"] = {**hsn, **_chk(o)}
    if o.fil_dt is not None:
        doc["fil_dt"] = _day(o.fil_dt)
    return doc


def _flag(o: Options, key: str, value: str) -> dict:
    return {key: value} if o.flags else {}


def _chk(o: Options) -> dict:
    return {"chksum": PLACEHOLDER_CHKSUM} if o.chksum == "placeholder" else {}


def _day(d: date) -> str:
    return f"{d:%d-%m-%Y}"


def _tax(a) -> dict:
    """The tax keys of a row, present only when not zero (a B2CS row writes all four itself)."""
    out: dict = {}
    for key, value in (("samt", a.sgst), ("iamt", a.igst), ("camt", a.cgst), ("csamt", a.cess)):
        if value != 0:
            out[key] = value
    return out


def _items(items: tuple[Item, ...]) -> list[dict]:
    return [
        {"num": n, "itm_det": {**_pick(_tax(i.amounts), "samt"), "rt": i.rate, "txval": i.amounts.taxable_value,
                               **_pick(_tax(i.amounts), "iamt", "camt", "csamt")}}
        for n, i in enumerate(items, 1)
    ]  # fmt: skip


def _pick(tax: dict, *keys: str) -> dict:
    return {k: tax[k] for k in keys if k in tax}


def _invoice(i: Invoice, o: Options, *, regular: bool = False) -> dict:
    out: dict = {"itms": _items(i.items), "val": i.value}
    if regular:
        out["inv_typ"] = "R"
    out.update(_flag(o, "flag", "U"))
    if regular:
        out["pos"] = i.pos
    out.update(_flag(o, "updby", "S"))
    out["idt"] = _day(i.date)
    if regular:
        out["rchrg"] = "N"
    out["inum"] = i.number
    out.update(_flag(o, "cflag", "N"))
    out.update(_chk(o))
    return out


def _small(r, o: Options) -> dict:
    a = r.amounts
    return {"samt": a.sgst, "csamt": a.cess, "rt": r.rate, **_flag(o, "flag", "N"), "pos": r.pos,
            "txval": a.taxable_value, "typ": "OE", "camt": a.cgst, **_chk(o), "iamt": a.igst,
            "sply_ty": "INTRA" if r.intra else "INTER"}  # fmt: skip


def _note(n: Note, o: Options, *, registered: bool) -> dict:
    out: dict = {}
    if not registered:
        out["typ"] = n.ur_type
    out.update({"ntty": n.kind, "nt_num": n.number, "nt_dt": _day(n.date), "val": n.value, "pos": n.pos})
    if registered:
        out.update({"rchrg": "N", "inv_typ": "R"})
    out["itms"] = _items(n.items)
    out.update(_flag(o, "flag", "U"))
    out.update(_flag(o, "updby", "S"))
    out.update(_flag(o, "cflag", "N"))
    out.update(_chk(o))
    return out


def _hsn(num: int, r: HsnLine) -> dict:
    return {"num": num, "hsn_sc": r.hsn, "uqc": r.uqc, "qty": r.quantity, "rt": r.rate, "txval": r.amounts.taxable_value,
            **_tax(r.amounts)}  # fmt: skip


# -- the writer: numbers are Decimals and never pass through a float -----------------------------------------------


def number(d: Decimal) -> str:
    """A JSON number: whole numbers without decimals, others with at most two and no trailing zero, never an exponent."""
    q = d.quantize(PAISE, rounding=ROUND_HALF_UP)
    if q == q.to_integral_value():
        return str(int(q))
    return format(q.normalize(), "f")


def dumps(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Decimal):
        return number(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return _string(value)
    if isinstance(value, dict):
        return "{" + ",".join(f"{_string(k)}:{dumps(v)}" for k, v in value.items()) + "}"
    if isinstance(value, list | tuple):
        return "[" + ",".join(dumps(v) for v in value) + "]"
    raise TypeError(f"cannot write {type(value).__name__} to the file")


def _string(s: str) -> str:
    import json

    return json.dumps(s, ensure_ascii=True)
