"""The sandboxed PDF read (R1-M6 S2a): a hard memory and time limit, and a bomb that fails cleanly."""

import os
import re
import sys
import time

import pytest

from app.modules.imports.pdf import Limits, PdfRefused
from app.modules.imports.pdf.sandbox import read_sandboxed

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
