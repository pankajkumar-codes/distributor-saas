"""The render pipeline's renderer half (D-042): input in, one PDF out; nothing fetched;
nothing written when a render fails. Inputs are never deleted (the lifecycle rule
expires them), and the renderer makes no delete call."""

import http.server
import json
import threading
import uuid

import pytest

BUCKET = "objects"


class S3Error(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class FakeS3:
    """The calls the renderer may make, over a dict. It has no delete: a delete call
    would fail the test. `fail_put` makes PutObject fail
    the way a network error would: before anything is stored."""

    def __init__(self):
        self.objects: dict[str, bytes] = {}
        self.calls: list[tuple[str, str]] = []
        self.fail_put = False

    def get_object(self, Bucket, Key):  # noqa: N803
        self.calls.append(("get", Key))
        if Key not in self.objects:
            raise S3Error("NoSuchKey")
        data = self.objects[Key]

        class Body:
            def read(self, n=-1):
                return data if n < 0 else data[:n]

        return {"Body": Body(), "ContentLength": len(data)}

    def put_object(self, Bucket, Key, Body, ContentType):  # noqa: N803
        self.calls.append(("put", Key))
        if self.fail_put:
            raise S3Error("RequestTimeout")
        assert ContentType == "application/pdf"
        self.objects[Key] = Body



def _doc(**fields):
    doc = {
        "v": 1, "template": "invoice-draft", "reverse_charge": "No",
        "seller": {"name": "Sample Traders", "gstin": "19AAAAA0000A1Z5", "address": ["1 Test Lane", "Kolkata 700001"],
                   "state": "West Bengal (19)"},
        "buyer": {"name": "Test Buyer", "gstin": None, "address": ["2 Other Road"], "state": "West Bengal (19)"},
        "ship_to": None, "doc_date": "2026-11-03", "place_of_supply": "West Bengal (19)",
        "lines": [{"no": "1", "description": "Notebook", "hsn": "4820", "quantity": "2", "uqc": "NOS",
                   "unit_price": "100.00", "discount": None}],
        "charges": [], "invoice_discount": "0.00", "totals": None,
        "note": "Tax and totals are worked out when you finalize.",
    }
    doc.update(fields)
    return doc


def _keys():
    b, r = uuid.uuid4(), uuid.uuid4()
    return f"render-input/b/{b}/{r}/input.json", f"documents/b/{b}/{r}/document.pdf"


def _event(key):
    return {"Records": [{"messageId": "m1", "body": json.dumps({"key": key})}]}


def test_an_input_becomes_one_pdf_and_the_input_is_left_for_the_lifecycle_rule():
    from renderer import handler

    s3, (key, out) = FakeS3(), _keys()
    s3.objects[key] = json.dumps(_doc()).encode()
    assert handler.sqs_handler(_event(key), s3, BUCKET) == {"batchItemFailures": []}
    pdf = s3.objects[out]
    assert pdf.startswith(b"%PDF-") and pdf.rstrip().endswith(b"%%EOF")
    assert key in s3.objects  # expired by the bucket's lifecycle rule, not deleted (D-042)
    assert [c[0] for c in s3.calls] == ["get", "put"]


def test_a_redelivered_message_renders_again_to_the_same_key():
    from renderer import handler

    s3, (key, out) = FakeS3(), _keys()
    s3.objects[key] = json.dumps(_doc()).encode()
    handler.sqs_handler(_event(key), s3, BUCKET)
    s3.calls.clear()
    assert handler.sqs_handler(_event(key), s3, BUCKET) == {"batchItemFailures": []}
    assert s3.calls == [("get", key), ("put", out)] and s3.objects[out].startswith(b"%PDF-")


def test_an_expired_input_fails_and_goes_to_the_dlq():
    """Without ListBucket S3 answers 403 for a missing key; either way it is a failure."""
    from renderer import handler

    s3, (key, out) = FakeS3(), _keys()
    assert handler.sqs_handler(_event(key), s3, BUCKET) == {"batchItemFailures": [{"itemIdentifier": "m1"}]}
    assert out not in s3.objects


@pytest.mark.parametrize("key", [
    "documents/b/{b}/{r}/document.pdf", "uploads/b/{b}/{r}", "render-input/b/{b}/{r}/other.json",
    "render-input/b/{b}/{r}", "../render-input/b/{b}/{r}/input.json",
])
def test_a_message_naming_anything_but_a_render_input_touches_nothing(key):
    from renderer import handler

    s3 = FakeS3()
    key = key.format(b=uuid.uuid4(), r=uuid.uuid4())
    assert handler.sqs_handler(_event(key), s3, BUCKET) == {"batchItemFailures": [{"itemIdentifier": "m1"}]}
    assert s3.calls == []


class _Server:
    """A local HTTP server that counts every request, to prove none arrives."""

    def __enter__(self):
        hits = self.hits = []

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                hits.append(self.path)
                self.send_response(200)
                self.end_headers()

            def log_message(self, *args):
                pass

        self.httpd = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()


def test_a_url_planted_in_any_field_is_printed_as_text_and_never_fetched():
    from renderer import handler, template

    with _Server() as srv:
        planted = [f'<img src="{srv.url}/img">', f'<link rel="stylesheet" href="{srv.url}/css">',
                   f"<style>@import url({srv.url}/import);</style>", f'"><iframe src="{srv.url}/frame">',
                   f"url({srv.url}/bare)"]
        doc = _doc(
            seller={"name": planted[0], "gstin": planted[1], "address": planted[2:], "state": "West Bengal (19)"},
            buyer={"name": planted[3], "address": [planted[4]]},
            lines=[{"no": "1", "description": planted[0], "hsn": planted[1], "quantity": "1", "uqc": planted[2],
                    "unit_price": "1.00", "discount": planted[3]}],
            charges=[{"label": planted[4], "amount": "1.00"}], note=planted[1],
        )
        html = template.render_html(doc)
        for tag in ("<img", "<link", "<iframe"):
            assert tag not in html
        assert html.count("<style>") == 1 and "@import" not in html.split("</style>", 1)[0]  # only our stylesheet
        assert "&lt;img src=&quot;http://127.0.0.1" in html
        s3, (key, out) = FakeS3(), _keys()
        s3.objects[key] = json.dumps(doc).encode()
        assert handler.sqs_handler(_event(key), s3, BUCKET) == {"batchItemFailures": []}
        assert out in s3.objects
    assert srv.hits == []


def test_the_fetcher_refuses_every_url_even_in_raw_html():
    """Second lock: even HTML that does ask for resources gets none of them."""
    from renderer import handler

    with _Server() as srv:
        html = (f'<html><head><link rel="stylesheet" href="{srv.url}/css">'
                f"<style>@import url({srv.url}/import); @font-face {{ font-family: X; src: url({srv.url}/font) }}"
                f" body {{ background: url({srv.url}/bg) }}</style></head>"
                f'<body><img src="{srv.url}/img"><img src="file:///etc/passwd">'
                '<img src="data:image/png;base64,iVBORw0KGgo="><img src="relative.png">x</body></html>')
        fetcher = handler.DenyAllFetcher()
        pdf = handler.render_pdf(html, fetcher)
    assert pdf.startswith(b"%PDF-")
    assert srv.hits == []
    assert {u.split("/")[-1] for u in fetcher.refused if u.startswith(srv.url)} >= {"css", "import", "img"}
    assert "file:///etc/passwd" in fetcher.refused
    assert any(u.startswith("data:") for u in fetcher.refused)


def test_a_render_that_fails_midway_writes_no_pdf_and_keeps_the_input(monkeypatch):
    from renderer import handler

    real = handler.weasyprint.Document.write_pdf

    def half_written(self, *args, **kwargs):
        real(self, *args, **kwargs)  # the PDF was being produced...
        raise MemoryError("out of memory")  # ...and the render died before returning it

    monkeypatch.setattr(handler.weasyprint.Document, "write_pdf", half_written)
    s3, (key, out) = FakeS3(), _keys()
    s3.objects[key] = json.dumps(_doc()).encode()
    assert handler.sqs_handler(_event(key), s3, BUCKET) == {"batchItemFailures": [{"itemIdentifier": "m1"}]}
    assert out not in s3.objects and key in s3.objects
    assert [c[0] for c in s3.calls] == ["get"]


def test_a_failed_write_keeps_the_input_for_the_retry():
    from renderer import handler

    s3, (key, out) = FakeS3(), _keys()
    s3.objects[key] = json.dumps(_doc()).encode()
    s3.fail_put = True
    assert handler.sqs_handler(_event(key), s3, BUCKET)["batchItemFailures"]
    assert out not in s3.objects and key in s3.objects
    s3.fail_put = False
    assert handler.sqs_handler(_event(key), s3, BUCKET) == {"batchItemFailures": []}
    assert out in s3.objects


@pytest.mark.parametrize("bad", [
    {"v": 2}, {"template": "other"}, {"lines": [{"no": 1, "description": "x", "quantity": "1", "unit_price": "1"}]},
    {"seller": {"name": "x" * 501}}, {"lines": "not a list"}, {"buyer": ["not", "an", "object"]},
])
def test_a_malformed_input_writes_no_pdf(bad):
    from renderer import handler

    s3, (key, out) = FakeS3(), _keys()
    s3.objects[key] = json.dumps(_doc(**bad)).encode()
    assert handler.sqs_handler(_event(key), s3, BUCKET)["batchItemFailures"]
    assert out not in s3.objects and key in s3.objects


def test_computed_fields_print_when_present():
    from renderer import template

    doc = _doc(lines=[{"no": "1", "description": "Notebook", "hsn": "4820", "quantity": "2", "uqc": "NOS",
                       "unit_price": "100.00", "taxable": "200.00", "rate": "12",
                       "taxes": [{"component": "CGST", "rate": "6", "amount": "12.00"},
                                 {"component": "SGST", "rate": "6", "amount": "12.00"}], "total": "224.00"}],
               totals={"taxable": "200.00", "taxes": [{"component": "CGST", "amount": "12.00"},
                                                      {"component": "SGST", "amount": "12.00"}],
                       "round_off": "0.00", "total": "224.00", "in_words": "Two hundred twenty-four rupees only"},
               note=None)
    html = template.render_html(doc)
    assert "Taxable value" in html and "CGST 6%: 12.00" in html and "224.00" in html and "Two hundred" in html
