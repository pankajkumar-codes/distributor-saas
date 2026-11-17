"""The gstr3b-worksheet template (render input v1): one or more tables of text, printed as given. A worksheet of numbers to
check and enter on the GST portal; the page says "Worksheet, not a filing" at the top (the input's `label`).

    {"v": 1, "template": "gstr3b-worksheet",
     "label": str, "subtitle": [str],            # the title line, then lines under it
     "banner"?: str,                             # e.g. "Out of date: ..."
     "sections": [{"title": str, "columns": [str], "rows": [{"label": str, "cells": [str | null]}]}],
     "notes": [str]}

Every value is a string, goes through `_t` (escaped, nothing placed in an attribute or style), and the template does no
arithmetic: amounts arrive as formatted decimal text, so the PDF shows what the screen and the Excel file show.
"""

from .template import MAX_LIST, _list, _obj, _t

MAX_SECTIONS = 12
MAX_ROWS = 60
MAX_COLUMNS = 6

STYLE = """
@page { size: A4; margin: 12mm }
body { font-family: "Noto Sans", "Noto Sans Devanagari", "Noto Sans Bengali"; font-size: 8.5pt; color: #000 }
h1 { font-size: 14pt; margin: 0 0 1mm }
h2 { font-size: 10pt; margin: 4mm 0 1mm }
.sub { margin: 0 0 1mm }
.banner { border: 1pt solid #000; padding: 1.5mm; margin: 2mm 0 }
table { width: 100%; border-collapse: collapse }
th, td { border: 0.5pt solid #555; padding: 1mm; vertical-align: top }
td.n, th.n { text-align: right; white-space: nowrap }
.notes { margin-top: 4mm }
"""


def render_html(doc: dict) -> str:
    """The whole page for one render input. Raises ValueError on a malformed input."""
    if _obj(doc) is None or doc.get("v") != 1 or doc.get("template") != "gstr3b-worksheet":
        raise ValueError("not a gstr3b-worksheet render input v1")
    out = [
        '<!doctype html><html lang="en"><meta charset="utf-8">',
        f"<style>{STYLE}</style><body>",
        f"<h1>{_t(doc.get('label'), optional=False)}</h1>",
    ]
    out += [f'<p class="sub">{_t(line, optional=False)}</p>' for line in _list(doc.get("subtitle"), MAX_LIST)]
    if doc.get("banner"):
        out.append(f'<div class="banner"><b>{_t(doc.get("banner"))}</b></div>')
    for sec in map(_obj, _list(doc.get("sections"), MAX_SECTIONS)):
        if sec is None:
            raise ValueError("render input section expected")
        columns = _list(sec.get("columns"), MAX_COLUMNS)
        out.append(f"<h2>{_t(sec.get('title'), optional=False)}</h2><table><tr><th></th>")
        out += [f'<th class="n">{_t(c, optional=False)}</th>' for c in columns]
        out.append("</tr>")
        for row in map(_obj, _list(sec.get("rows"), MAX_ROWS)):
            if row is None:
                raise ValueError("render input row expected")
            cells = _list(row.get("cells"), MAX_COLUMNS)
            out.append(f"<tr><td>{_t(row.get('label'), optional=False)}</td>")
            out += [f'<td class="n">{_t(c)}</td>' for c in cells]
            out.append("</tr>")
        out.append("</table>")
    notes = [_t(n, optional=False) for n in _list(doc.get("notes"), MAX_LIST)]
    if notes:
        out.append('<div class="notes"><ul>' + "".join(f"<li>{n}</li>" for n in notes) + "</ul></div>")
    out.append("</body></html>")
    return "".join(out)
