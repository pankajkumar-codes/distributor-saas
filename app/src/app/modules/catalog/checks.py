"""Product field checks (LLD-3 §4). Limits and lists come from refdata; nothing here
picks or suggests a value, it only refuses one that can't be right."""

import re
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.modules.refdata import uqc_name, value_on
from platform_common.errors import Invalid

CODE = re.compile(r"^[A-Za-z0-9_./-]+$")
# The column holds 18 digits with 2 after the point.
SALE_RATE = re.compile(r"^[0-9]{1,16}(\.[0-9]{1,2})?$")
TAX_CATEGORIES = ("taxable", "exempt", "nil_rated", "non_gst")


def code(tx: Session, raw: str, today: date) -> str:
    value = (raw or "").strip()
    limit = int(value_on(tx, "catalog.product_code.max_length", today))
    if not value or len(value) > limit or not CODE.match(value):
        raise Invalid(
            "code_invalid",
            f"Use 1 to {limit} letters, digits, or - _ / .",
            field="code",
        )
    return value


def name(raw: str) -> str:
    value = (raw or "").strip()
    if not value or len(value) > 200:
        raise Invalid("name_invalid", "Enter a name of up to 200 characters", field="name")
    return value


def hsn(tx: Session, raw: str | None, today: date) -> str | None:
    """Blank means "Missing HSN". Otherwise the shape in refdata hsn.pattern (4, 6 or 8
    digits today, provisional): a typo check only, never which HSN fits (GC-P3)."""
    value = (raw or "").strip()
    if not value:
        return None
    if not value_on(tx, "hsn.pattern", today).fullmatch(value):
        raise Invalid("hsn_invalid", "HSN is 4, 6 or 8 digits, with no spaces", field="hsn")
    return value


def uqc(tx: Session, raw: str, today: date) -> str:
    value = (raw or "").strip().upper()
    if uqc_name(tx, value, today) is None:
        raise Invalid("uqc_unknown", "Choose a unit from the list", field="uqc")
    return value


def sale_rate(raw: str) -> Decimal:
    """Per unit, excluding GST [RM43-3]. A decimal string only: never a float (AC3-15)."""
    if not isinstance(raw, str) or not SALE_RATE.match(raw.strip()):
        raise Invalid("sale_rate_invalid", "Enter the price as a number with up to 2 decimals, like 120.50",
                      field="sale_rate")
    return Decimal(raw.strip())


def barcode(raw: str | None) -> str | None:
    value = (raw or "").strip()
    if not value:
        return None
    if len(value) > 64 or not value.isprintable():
        raise Invalid("barcode_invalid", "A barcode is up to 64 printable characters", field="barcode")
    return value


def tax_category(raw: str) -> str:
    if raw not in TAX_CATEGORIES:
        raise Invalid("tax_category_invalid", f"Choose one of {', '.join(TAX_CATEGORIES)}", field="tax_category")
    return raw
