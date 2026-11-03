"""The renderer Lambda's entry point, renderer.handler.handler (TD-9, D-042).

S4 (BH-6) adds the invoice task: after finalize the worker sends a message to the
`render` SQS queue, which triggers this function (D-042). The message carries a document
ID or an S3 key, never the invoice itself. Until then a queue message is refused (and
lands in the DLQ after five tries), and the only task is the self-test, invoked by hand, which renders a fixed one-page
sample (fictional names and amounts; English, Hindi and the rupee sign) and reports its
size and render time. It reads and writes nothing, so it is safe to invoke by hand, and
it is how the arm64 numbers get measured on the first staging deploy.
"""

import re
import time

from renderer import boot  # noqa: F401  must come before weasyprint

import weasyprint  # noqa: E402

SAMPLE = """<!doctype html><html lang="en"><meta charset="utf-8"><style>
@page { size: A4; margin: 15mm }
body { font-family: "Noto Sans", "Noto Sans Devanagari"; font-size: 10pt }
td.amt { text-align: right }
</style><body>
<h1>Sample Traders <span lang="hi">श्री गणेश ट्रेडर्स</span></h1>
<p>Self-test page; not a tax invoice.</p>
<table><tr><th>Item</th><th>Amount</th></tr>
<tr><td>Notebook <span lang="hi">कॉपी</span></td><td class="amt">₹ 1,250.00</td></tr>
<tr><td><b>Total <span lang="hi">कुल</span></b></td><td class="amt"><b>₹ 1,250.00</b></td></tr>
</table></body></html>"""


def selftest() -> dict:
    start = time.perf_counter()
    document = weasyprint.HTML(string=SAMPLE).render()
    pdf = document.write_pdf(uncompressed_pdf=True)  # so the font names can be read below
    return {
        "pages": len(document.pages),
        "bytes": len(pdf),
        "render_ms": round((time.perf_counter() - start) * 1000),
        "fonts": sorted({m.decode() for m in re.findall(rb"/BaseFont\s*/[A-Z]{6}\+([\w-]+)", pdf)}),
    }


def handler(event, context):  # noqa: ARG001
    if event.get("task") == "selftest":
        return selftest()
    raise ValueError(f"unknown renderer task {event.get('task')!r}")
