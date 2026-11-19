"""The paid reader against a fake client only: no AWS call, no credentials."""

import json
import logging

import pytest

from app.modules.imports.pdf import Limits, PdfRefused
from app.modules.imports.pdf.bedrock_reader import BedrockReader
from app.modules.imports.pdf.interface import InvoiceReader

LIMITS = Limits(max_pages=20, max_chars_per_page=5000, max_documents=10, max_seconds=30)
PDF = b"%PDF-1.4 synthetic"
GOOD = {"invoices": [{
    "pages": [1], "doc_type": "Invoice", "seller_gstin": "19AAAAA0000A1Z5", "doc_number": "INV-1",
    "doc_date": "03-07-2026", "buyer_gstin": None, "place_of_supply": "19", "invoice_total": "118.00",
    "lines": [{"page": 1, "hsn": "6109", "quantity": "2", "unit": "PCS", "taxable_value": "100.00",
               "gst_rate": "18", "cgst": "9.00", "sgst": "9.00"}],
}]}


class Fake:
    def __init__(self, text=None, error=None):
        self.calls = []
        self._text, self._error = text, error

    def converse(self, **kw):
        self.calls.append(kw)
        if self._error:
            raise self._error
        return {"output": {"message": {"content": [{"text": self._text}]}}}


def reader(fake, enabled=True, profile="anthropic.test-model-v1:0"):
    r: InvoiceReader = BedrockReader(fake, profile, enabled)
    return r


def test_it_is_off_by_default_and_makes_no_call():
    fake = Fake(json.dumps(GOOD))
    for r in (BedrockReader(fake, "p"), reader(fake, enabled=False)):
        with pytest.raises(PdfRefused) as e:
            r.read(PDF, LIMITS)
        assert e.value.code == "pdf_paid_reader_off"
    assert fake.calls == []


def test_without_a_profile_id_it_refuses_and_makes_no_call():
    fake = Fake(json.dumps(GOOD))
    with pytest.raises(PdfRefused) as e:
        reader(fake, profile=" ").read(PDF, LIMITS)
    assert e.value.code == "pdf_paid_reader_not_configured" and fake.calls == []


def test_a_good_reply_gives_the_same_shape_as_the_text_reader():
    fake = Fake(json.dumps(GOOD))
    (inv,) = reader(fake).read(PDF, LIMITS).invoices
    assert fake.calls[0]["modelId"] == "anthropic.test-model-v1:0" and fake.calls[0]["inferenceConfig"]["temperature"] == 0
    assert (inv.doc_number, inv.doc_date, inv.invoice_total, inv.pages) == ("INV-1", "03-07-2026", "118.00", (1,))
    assert inv.unclear == {"buyer_gstin"}
    assert inv.lines[0].cgst == "9.00" and inv.lines[0].igst is None and not inv.lines[0].unclear


def test_values_that_do_not_fit_are_blanked_and_named_not_repaired():
    bad = json.loads(json.dumps(GOOD))
    bad["invoices"][0].update(doc_date="3 July 2026", invoice_total="1,18.00", doc_type="Receipt")
    bad["invoices"][0]["lines"][0].update(taxable_value=100.0, hsn=None)
    (inv,) = reader(Fake(json.dumps(bad))).read(PDF, LIMITS).invoices
    assert inv.doc_date is None and inv.invoice_total is None and inv.doc_type is None
    assert {"doc_date", "invoice_total", "doc_type"} <= inv.unclear
    assert inv.lines[0].taxable_value is None and inv.lines[0].unclear == {"taxable_value", "hsn"}


@pytest.mark.parametrize("reply", [
    "not json", "[]", json.dumps({"invoices": "x"}), json.dumps({"invoices": [{"pages": [], "lines": []}]}),
    json.dumps({"invoices": [{"pages": [99], "lines": []}]}),
    json.dumps({"invoices": [{"pages": [True], "lines": []}]}),
    json.dumps({"invoices": [{"pages": [1], "lines": [{"page": 2}]}]}),
    json.dumps({"invoices": [GOOD["invoices"][0]] * 11}),
])
def test_a_malformed_or_oversized_reply_is_refused(reply):
    with pytest.raises(PdfRefused) as e:
        reader(Fake(reply)).read(PDF, LIMITS)
    assert e.value.code == "pdf_paid_reader_failed"


@pytest.mark.parametrize("bad", [[], {}, ["Invoice"], {"a": 1}, 5, None])
def test_a_doc_type_that_is_not_text_is_blank_not_a_crash(bad):
    reply = json.loads(json.dumps(GOOD))
    reply["invoices"][0]["doc_type"] = bad
    (inv,) = reader(Fake(json.dumps(reply))).read(PDF, LIMITS).invoices
    assert inv.doc_type is None and "doc_type" in inv.unclear


def test_an_unexpected_fault_while_checking_the_reply_is_the_plain_refusal(monkeypatch):
    from app.modules.imports.pdf import bedrock_reader

    def boom(*a, **k):
        raise TypeError("19AAAAA0000A1Z5")

    monkeypatch.setattr(bedrock_reader, "_validate", boom)
    with pytest.raises(PdfRefused) as e:
        reader(Fake(json.dumps(GOOD))).read(PDF, LIMITS)
    assert str(e.value) == "pdf_paid_reader_failed" and e.value.__cause__ is None


def test_a_client_error_is_a_plain_refusal_with_no_cause_and_no_value_logged(caplog):
    caplog.set_level(logging.DEBUG)
    with pytest.raises(PdfRefused) as e:
        reader(Fake(error=RuntimeError("secret 19AAAAA0000A1Z5"))).read(PDF, LIMITS)
    assert str(e.value) == "pdf_paid_reader_failed" and e.value.__cause__ is None
    assert "19AAAAA" not in caplog.text and "19AAAAA" not in repr(e.value)


def test_a_non_pdf_or_oversized_file_is_refused_before_anything_is_sent():
    fake = Fake(json.dumps(GOOD))
    for data, code in ((b"hello", "pdf_not_a_pdf"), (PDF + b"0" * 4_600_000, "pdf_too_large")):
        with pytest.raises(PdfRefused) as e:
            reader(fake).read(data, LIMITS)
        assert e.value.code == code
    assert fake.calls == []


def test_the_same_file_read_twice_gives_the_same_result():
    fake = Fake(json.dumps(GOOD))
    assert reader(fake).read(PDF, LIMITS) == reader(fake).read(PDF, LIMITS)


@pytest.mark.parametrize("profile", [
    "us.anthropic.test-model-v1:0", "eu.anthropic.test-model-v1:0", "apac.anthropic.test-model-v1:0",
    "global.anthropic.test-model-v1:0", "arn:aws:bedrock:us-east-1:123456789012:inference-profile/x", "profile-x",
    "arn:aws:bedrock:ap-south-1:123456789012:inference-profile/apac.anthropic.test-model-v1:0",
    "arn:aws:bedrock:ap-south-1:123456789012:application-inference-profile/abc123",
])
def test_a_profile_that_could_send_the_document_out_of_india_is_refused_and_makes_no_call(profile):
    fake = Fake(json.dumps(GOOD))
    with pytest.raises(PdfRefused) as e:
        reader(fake, profile=profile).read(PDF, LIMITS)
    assert e.value.code == "pdf_paid_reader_region_refused" and fake.calls == []


def test_an_indian_foundation_model_arn_is_accepted():
    fake = Fake(json.dumps(GOOD))
    arn = "arn:aws:bedrock:ap-south-1::foundation-model/anthropic.test-model-v1:0"
    reader(fake, profile=arn).read(PDF, LIMITS)
    assert fake.calls[0]["modelId"] == arn
