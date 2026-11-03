"""The renderer Lambda's entry point, renderer.handler.handler (TD-9, D-042).

Two kinds of event:
- an SQS batch from the `render` queue (batch size 1). Each message is `{"key": <S3 key
  of a render input>}`; the input is JSON under render-input/b/ (platform_common.render).
  The renderer reads it, renders the PDF in memory and writes it in one PutObject to
  documents/b/<business>/<render>/document.pdf. A failure anywhere before the PutObject
  writes nothing, so there is never a partial PDF; the message comes back and, after
  five tries, lands in the DLQ. The input is never deleted: the lifecycle rule expires
  it after a day (D-042). A redelivered message renders again to the same key; one
  whose input has expired fails (the renderer can't list the bucket, so S3 answers 403)
  and goes to the DLQ.
- `{"task": "selftest"}`, invoked by hand: renders a fixed one-page sample (fictional
  names and amounts; English, Hindi and the rupee sign) and reports size and time. It
  reads and writes nothing, so it is how the arm64 numbers get measured.

Rendering fetches nothing (D-042): `DenyAllFetcher` refuses every URL, whatever its
scheme, so no field can make the renderer reach the network, the file system or another
AWS service; the template also escapes every field (renderer.template). Nothing from a
render input is logged.
"""

import json
import logging
import os
import re
import time

from renderer import boot  # noqa: F401  must come before weasyprint

import weasyprint  # noqa: E402
from weasyprint.urls import URLFetcher  # noqa: E402

from renderer import inputs, template  # noqa: E402

log = logging.getLogger()
log.setLevel(logging.INFO)

MAX_INPUT_BYTES = 1024 * 1024  # platform_common.render.MAX_INPUT_BYTES

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


class DenyAllFetcher(URLFetcher):
    """Refuses every URL: http(s), file, data, anything. WeasyPrint treats the refusal as
    a missing resource and carries on, so a planted URL costs nothing but a warning.
    `refused` lists what was asked for, for the tests."""

    def __init__(self):
        super().__init__(allowed_protocols=(), allow_redirects=False, timeout=1)
        self.refused: list[str] = []

    def fetch(self, url, headers=None):  # noqa: ARG002
        self.refused.append(url)
        raise ValueError("the renderer fetches nothing")


def render_pdf(html: str, fetcher: DenyAllFetcher | None = None) -> bytes:
    """The whole PDF in memory. No base URL, so even a relative URL has nowhere to go."""
    fetcher = fetcher or DenyAllFetcher()
    return weasyprint.HTML(string=html, base_url=None, url_fetcher=fetcher).write_pdf()


def selftest() -> dict:
    start = time.perf_counter()
    document = weasyprint.HTML(string=SAMPLE, url_fetcher=DenyAllFetcher()).render()
    pdf = document.write_pdf(uncompressed_pdf=True)  # so the font names can be read below
    return {
        "pages": len(document.pages),
        "bytes": len(pdf),
        "render_ms": round((time.perf_counter() - start) * 1000),
        "fonts": sorted({m.decode() for m in re.findall(rb"/BaseFont\s*/[A-Z]{6}\+([\w-]+)", pdf)}),
    }


def render_one(s3, bucket: str, key: str) -> str:
    """Renders one input. Returns "rendered"; raises on anything to retry."""
    out = inputs.document_key(key)  # refuses anything but render-input/b/<b>/<r>/input.json
    obj = s3.get_object(Bucket=bucket, Key=key)
    if int(obj.get("ContentLength", 0)) > MAX_INPUT_BYTES:
        raise ValueError("render input too large")
    body = obj["Body"].read(MAX_INPUT_BYTES + 1)
    if len(body) > MAX_INPUT_BYTES:
        raise ValueError("render input too large")
    pdf = render_pdf(template.render_html(json.loads(body)))
    # One PutObject: S3 shows the whole object or none of it. The bucket's default
    # encryption (SSE-KMS, our key) applies.
    s3.put_object(Bucket=bucket, Key=out, Body=pdf, ContentType="application/pdf")
    return "rendered"


def _s3():
    import boto3  # in the Lambda runtime; imported here so tests and the self-test need none
    from botocore.config import Config

    return boto3.client("s3", config=Config(connect_timeout=2, read_timeout=5,
                                            retries={"mode": "standard", "total_max_attempts": 3}))


def sqs_handler(event, s3=None, bucket: str | None = None) -> dict:
    s3 = s3 or _s3()
    bucket = bucket or os.environ["OBJECTS_BUCKET"]
    failures = []
    for record in event.get("Records", []):
        message_id = record.get("messageId")
        try:
            key = json.loads(record["body"])["key"]
            start = time.perf_counter()
            outcome = render_one(s3, bucket, key)
            log.info("render %s: %s in %d ms", message_id, outcome, (time.perf_counter() - start) * 1000)
        except Exception as e:
            # The type only: a message could quote the input.
            log.error("render %s failed: %s", message_id, type(e).__name__)
            failures.append({"itemIdentifier": message_id})
    return {"batchItemFailures": failures}


def handler(event, context):  # noqa: ARG001
    if "Records" in event:
        return sqs_handler(event)
    if event.get("task") == "selftest":
        return selftest()
    raise ValueError(f"unknown renderer task {event.get('task')!r}")
