"""Synthetic own-invoice PDFs for tests (R1-M6): written byte by byte here, standard Helvetica, no library.
Every value is made up. A page is a list of (x, y, text) placements."""

SELLER = "19DEMOA1234A1Z5"
BUYER = "29DEMOC9999C1Z1"
PAGE_H = 800


def pdf(pages, *, extra_objects=(), catalog_extra=""):
    """pages: list of lists of (x, y, text). Returns the PDF bytes."""
    objs = {}
    n_pages = len(pages)
    first_page = 4
    kids = " ".join(f"{first_page + 2 * i} 0 R" for i in range(n_pages))
    objs[1] = f"<< /Type /Catalog /Pages 2 0 R {catalog_extra} >>".encode()
    objs[2] = f"<< /Type /Pages /Kids [{kids}] /Count {n_pages} >>".encode()
    objs[3] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    for i, items in enumerate(pages):
        p = first_page + 2 * i
        body = "BT /F1 9 Tf\n"
        for x, y, text in items:
            esc = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            body += f"1 0 0 1 {x} {y} Tm ({esc}) Tj\n"
        body += "ET"
        objs[p] = (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 {PAGE_H}] /Contents {p + 1} 0 R "
                   f"/Resources << /Font << /F1 3 0 R >> >> >>").encode()
        objs[p + 1] = f"<< /Length {len(body)} >>\nstream\n{body}\nendstream".encode()
    nxt = first_page + 2 * n_pages
    for extra in extra_objects:
        objs[nxt] = extra
        nxt += 1
    out = bytearray(b"%PDF-1.4\n")
    offsets = {}
    for num in sorted(objs):
        offsets[num] = len(out)
        out += f"{num} 0 obj\n".encode() + objs[num] + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {nxt}\n0000000000 65535 f \n".encode()
    for num in range(1, nxt):
        out += f"{offsets[num]:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {nxt} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


COLS = {"sno": 40, "desc": 70, "hsn": 190, "qty": 245, "unit": 290, "taxable": 335, "rate": 400, "cgst": 445,
        "sgst": 490, "igst": 535}


def invoice_page(number="INV-1", *, title="TAX INVOICE", date="03-07-2026", seller=SELLER, buyer=BUYER,
                 place="West Bengal (19)", lines=(("6109", "2", "PCS", "200.00", "18", "18.00", "18.00", ""),),
                 total="236.00", original=None, number_label="Invoice No", date_label="Invoice Date",
                 header_extra=(), y0=760):
    items = [(40, y0, title), (40, y0 - 14, "Demo Seller Pvt Ltd"), (40, y0 - 26, f"GSTIN: {seller}"),
             (330, y0 - 14, f"{number_label}: {number}"), (330, y0 - 26, f"{date_label}: {date}")]
    y = y0 - 40
    if original:
        items.append((330, y, f"Original Invoice No: {original[0]}"))
        items.append((330, y - 12, f"Original Invoice Date: {original[1]}"))
        y -= 24
    items.append((40, y, "Bill To:"))
    items.append((40, y - 12, "Demo Buyer"))
    if buyer:
        items.append((40, y - 24, f"GSTIN: {buyer}"))
    items.append((330, y - 12, f"Place of Supply: {place}"))
    items.extend(header_extra)
    y -= 50
    head = [("sno", "S.No"), ("desc", "Description"), ("hsn", "HSN/SAC"), ("qty", "Qty"), ("unit", "Unit"),
            ("taxable", "Taxable Value"), ("rate", "GST %"), ("cgst", "CGST"), ("sgst", "SGST"), ("igst", "IGST")]
    for key, text in head:
        items.append((COLS[key], y, text))
    for i, (hsn, qty, unit, taxable, rate, cgst, sgst, igst) in enumerate(lines, start=1):
        y -= 14
        for key, text in (("sno", str(i)), ("desc", "Item description"), ("hsn", hsn), ("qty", qty), ("unit", unit),
                          ("taxable", taxable), ("rate", rate), ("cgst", cgst), ("sgst", sgst), ("igst", igst)):
            if text:
                items.append((COLS[key], y, text))
    y -= 20
    if total is not None:
        items.append((330, y, "Grand Total"))
        items.append((490, y, total))
    items.append((40, y - 30, "Amount in words: Demo only"))
    return items


def one_invoice(**kw):
    return pdf([invoice_page(**kw)])


def bomb(expanded_bytes: int) -> bytes:
    """A small PDF whose one content stream is Flate-compressed and expands to `expanded_bytes` of blanks: the
    shape of a decompression bomb. About 1 KB per 1 MB expanded."""
    import zlib

    co = zlib.compressobj(9)
    chunk = b" " * (1024 * 1024)
    parts = [co.compress(b"BT /F1 9 Tf 1 0 0 1 40 700 Tm (bomb) Tj ET\n")]
    for _ in range(expanded_bytes // len(chunk)):
        parts.append(co.compress(chunk))
    parts.append(co.flush())
    data = b"".join(parts)
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [4 0 R] /Count 1 >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 800] /Contents 5 0 R "
        b"/Resources << /Font << /F1 3 0 R >> >> >>",
        b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(data) + data + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for n, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % n + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return bytes(out)
