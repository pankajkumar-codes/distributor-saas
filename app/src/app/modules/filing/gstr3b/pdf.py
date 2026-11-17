"""The render input of the GSTR-3B worksheet PDF (template `gstr3b-worksheet`, renderer/renderer/worksheet_template.py). Pure.

The same figures and the same row labels as the screen and the Excel file: amounts are the stored decimal text, never worked out
again here, and the text says "Worksheet, not a filing" and that offset and payment are done on the GST portal.
"""

from .entries import net_itc
from .excel import HEAD_TITLES, NOT_BUILT, SheetModel
from .labels import (
    NET_ITC_LABEL,
    OFFSET_NOTE,
    PORTAL_NOTE,
    TABLE_3_1,
    TABLE_3_1_1_NOTE,
    TABLE_4_AVAILABLE,
    TABLE_4_OTHER,
    TABLE_4_REVERSED,
    TABLE_5,
    TABLE_5_1,
    WORKSHEET_LABEL,
    Row,
)
from .worksheet import FLAG_TEXT

OUT_OF_DATE = "Out of date: your GSTR-1 has changed since this build. Build the worksheet again before you use it."
NO_BUYER_TYPES = "Supplies to composition dealers and UIN holders are not known to this worksheet; check on the GST portal."
ZERO = "0.00"
TAX = ("igst", "cgst", "sgst", "cess")


def _rows(table: str, rows: tuple[Row, ...], entries: dict[str, str], heads: tuple[str, ...]) -> list[dict]:
    return [
        {"label": r.label, "cells": [entries.get(f"{table}.{r.key}.{h}", "") if h in r.heads else "" for h in heads]}
        for r in rows
    ]


def render_input(m: SheetModel) -> dict:
    taxable = m.outward["taxable"]
    heads31 = ("taxable_value", *TAX)
    rows31 = []
    for row in TABLE_3_1:
        if row.key == "a":
            cells = [taxable[h] for h in heads31]
        elif row.key == "d":
            cells = [m.entries.get(f"t3_1.d.{h}", "") for h in heads31]
        else:
            cells = [ZERO] * len(heads31)
            rows31.append({"label": f"{row.label} ({NOT_BUILT})", "cells": cells})
            continue
        rows31.append({"label": row.label, "cells": cells})
    sections = [
        {"title": "3.1 Details of Outward Supplies and inward supplies liable to reverse charge",
         "columns": [HEAD_TITLES[h] for h in heads31], "rows": rows31},
        {"title": "3.2 Of the supplies shown in 3.1(a), inter-State supplies made to unregistered persons",
         "columns": ["Place of Supply (State code)", "Total Taxable Value", HEAD_TITLES["igst"]],
         "rows": [{"label": "Supplies made to Unregistered Persons",
                   "cells": [s["pos_state_code"], s["unregistered_taxable"], s["unregistered_igst"]]}
                  for s in m.outward["inter_state"]]},
        {"title": "4. Eligible ITC (typed by you; the app does not check it)", "columns": [HEAD_TITLES[h] for h in TAX],
         "rows": [
             {"label": "(A) ITC Available (whether in full or part)", "cells": []},
             *_rows("t4a", TABLE_4_AVAILABLE, m.entries, TAX),
             {"label": "(B) ITC Reversed", "cells": []},
             *_rows("t4b", TABLE_4_REVERSED, m.entries, TAX),
             {"label": NET_ITC_LABEL, "cells": [net_itc(m.entries)[h] for h in TAX]},
             {"label": "(D) Other Details", "cells": []},
             *_rows("t4d", TABLE_4_OTHER, m.entries, TAX),
         ]},
        {"title": "5. Values of exempt, nil-rated and non-GST inward supplies",
         "columns": ["Inter-State supplies", "Intra-State supplies"],
         "rows": _rows("t5", TABLE_5, m.entries, ("inter", "intra"))},
        {"title": "5.1 Interest", "columns": [HEAD_TITLES[h] for h in TAX], "rows": _rows("t5_1", TABLE_5_1, m.entries, TAX)},
    ]
    notes = [TABLE_3_1_1_NOTE, NO_BUYER_TYPES, OFFSET_NOTE, *(FLAG_TEXT[c] for c in m.flags)]
    return {
        "template": "gstr3b-worksheet",
        "label": WORKSHEET_LABEL,
        "subtitle": [
            PORTAL_NOTE,
            f"GSTIN {m.gstin}, period {m.period_label}",
            f"Built from your GSTR-1 as version {m.version} on {m.built_at}. File made on {m.generated_at}.",
        ],
        "banner": OUT_OF_DATE if m.out_of_date else None,
        "sections": sections,
        "notes": notes,
    }
