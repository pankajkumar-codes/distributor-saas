"""The sandboxed PDF read (R1-M6 S2a): a hard memory and time limit, and a bomb that fails cleanly."""

import os
import re
import sys
import time

import pytest

from app.modules.imports.pdf import Limits, PdfRefused
from app.modules.imports.pdf.sandbox import SandboxUnavailable, read_sandboxed

from .fixtures.pdf import SELLER, bomb, one_invoice, pdf

HSN = "^[0-9]{4}([0-9]{2}){0,2}$"
LIMITS = Limits(max_pages=20, max_chars_per_page=5000, max_documents=10, max_seconds=20)
MEMORY = 768 * 1024 * 1024
linux_only = pytest.mark.skipif(sys.platform != "linux", reason="RLIMIT_AS is enforced on Linux")


def run(data, limits=LIMITS, memory=MEMORY):
    return read_sandboxed(data, limits, HSN, max_memory_bytes=memory)


def test_the_child_returns_the_same_result_as_the_in_process_reader():
    from app.modules.imports.pdf import TextLayerReader

    data = one_invoice()
    assert run(data) == TextLayerReader(re.compile(HSN)).read(data, LIMITS)
    (inv,) = run(data).invoices
    assert inv.seller_gstin == SELLER and inv.lines[0].unclear == frozenset()


@pytest.mark.parametrize("data,code", [(b"hello", "not_a_pdf"), (one_invoice()[:150], "unreadable")])
def test_a_refusal_in_the_child_comes_back_as_the_same_code(data, code):
    with pytest.raises(PdfRefused) as e:
        run(data)
    assert e.value.code == code


def test_the_child_enforces_the_page_cap():
    with pytest.raises(PdfRefused) as e:
        run(pdf([[(40, 700, "page")]] * 3), Limits(2, 5000, 10, 20))
    assert e.value.code == "too_many_pages"


@linux_only
def test_a_decompression_bomb_fails_cleanly_inside_the_memory_limit():
    data = bomb(400 * 1024 * 1024)  # about 400 KB on disk, 400 MB once decoded
    assert len(data) < 2 * 1024 * 1024
    started = time.monotonic()
    with pytest.raises(PdfRefused) as e:
        run(data, memory=512 * 1024 * 1024)
    assert e.value.code in ("too_complex", "unreadable")
    assert time.monotonic() - started < 30  # fails, and never hangs the queue


@linux_only
def test_the_same_bomb_would_read_fine_without_the_limit_which_is_why_it_exists():
    from app.modules.imports.pdf import TextLayerReader

    # Not the bomb itself (that would use the memory we are guarding): one a tenth the size, in this process,
    # reads to a result, so the failure above comes from the limit and not from a broken fixture.
    data = bomb(40 * 1024 * 1024)
    assert TextLayerReader(re.compile(HSN)).read(data, LIMITS).unreadable_pages in ((), (1,))


def test_the_wall_clock_kills_a_child_that_runs_too_long(monkeypatch):
    import subprocess

    def slow(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="x", timeout=1)

    monkeypatch.setattr(subprocess, "run", slow)
    with pytest.raises(PdfRefused) as e:
        run(one_invoice())
    assert e.value.code == "too_slow"


def test_a_parser_that_cannot_be_started_is_not_a_refusal_of_the_file(monkeypatch):
    import subprocess

    def cannot(*args, **kwargs):
        raise OSError("fork failed: /secret/path")

    monkeypatch.setattr(subprocess, "run", cannot)
    with pytest.raises(SandboxUnavailable) as e:
        run(one_invoice())
    assert not isinstance(e.value, PdfRefused) and "/secret" not in str(e.value)


def test_the_child_gets_no_environment_beyond_the_code_path(monkeypatch):
    import subprocess

    seen = {}
    real = subprocess.run

    def spy(*args, **kwargs):
        seen.update(kwargs["env"])
        return real(*args, **kwargs)

    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "do-not-leak")
    monkeypatch.setattr(subprocess, "run", spy)
    run(one_invoice())
    assert set(seen) == {"PYTHONPATH", "PYTHONHASHSEED"} and "do-not-leak" not in "".join(seen.values())
    assert all(os.path.isabs(p) for p in seen["PYTHONPATH"].split(os.pathsep))


def test_a_child_that_dies_without_an_answer_is_a_clean_refusal(monkeypatch):
    import subprocess

    class Dead:
        stdout, returncode = b"", -9

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Dead())
    with pytest.raises(PdfRefused) as e:
        run(one_invoice())
    assert e.value.code == "too_complex"


def test_an_answer_of_the_wrong_shape_is_a_refusal_not_a_crash(monkeypatch):
    import subprocess

    class Odd:
        stdout, returncode = b'{"invoices": [{"nope": 1}], "unreadable_pages": []}', 0

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Odd())
    with pytest.raises(PdfRefused) as e:
        run(one_invoice())
    assert e.value.code == "unreadable"


FORGED = [
    b"null", b"123", b'"refused"', b'["refused"]', b"[]",
    b'{"refused": {"a": 1}}', b'{"refused": 7}',
    b'{"invoices": [], "unreadable_pages": [], "extra": 1}',
    b'{"invoices": "x", "unreadable_pages": []}',
    b'{"invoices": [], "unreadable_pages": [0]}',
    b'{"invoices": [], "unreadable_pages": [true]}',
    b'{"invoices": [], "unreadable_pages": [999]}',
]


@pytest.mark.parametrize("answer", FORGED)
def test_a_forged_answer_is_a_refusal_and_never_a_crash_or_an_odd_code(monkeypatch, answer):
    import subprocess

    class Forged:
        stdout, returncode = answer, 0

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Forged())
    with pytest.raises(PdfRefused) as e:
        run(one_invoice())
    assert e.value.code == "unreadable"


def _answer(**overrides):
    import json

    from app.modules.imports.pdf import TextLayerReader
    from app.modules.imports.pdf.sandbox import to_json

    base = json.loads(to_json(TextLayerReader(re.compile(HSN)).read(one_invoice(), LIMITS)))
    inv = base["invoices"][0]
    for key, value in overrides.items():
        target = inv["lines"][0] if key.startswith("line_") else inv
        target[key.removeprefix("line_")] = value
    return json.dumps(base).encode()


@pytest.mark.parametrize("override", [
    {"doc_number": {"a": 1}}, {"doc_number": "x" * 101}, {"line_hsn": ["6109"]}, {"pages": [1, "2"]},
    {"unclear": ["a"] * 21}, {"line_page": 99}, {"lines": "nope"}, {"seller_gstin": 5},
])
def test_a_well_shaped_answer_with_a_bad_field_is_refused(monkeypatch, override):
    import subprocess

    class Odd:
        stdout, returncode = _answer(**override), 0

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Odd())
    with pytest.raises(PdfRefused) as e:
        run(one_invoice())
    assert e.value.code == "unreadable"


def test_a_good_answer_passes_the_check(monkeypatch):
    import subprocess

    class Fine:
        stdout, returncode = _answer(), 0

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Fine())
    assert run(one_invoice()).invoices[0].doc_number == "INV-1"


def test_more_documents_than_the_cap_in_an_answer_is_refused(monkeypatch):
    import json
    import subprocess

    base = json.loads(_answer())
    base["invoices"] = base["invoices"] * 11

    class Many:
        stdout, returncode = json.dumps(base).encode(), 0

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Many())
    with pytest.raises(PdfRefused):
        run(one_invoice())
