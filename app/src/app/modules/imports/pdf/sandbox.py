"""Reads a PDF in a child process with a hard memory and time limit (R1-M6 S2a; the gate Staff 2 (3) set on #140).

pdfminer decodes a page's streams before any cap of ours can look at the result, so a 300 KB PDF whose compressed
stream expands to hundreds of MB would use that much memory inside the worker. The parse therefore never runs in the
worker: the worker starts `python -m app.modules.imports.pdf.worker`, sends it the PDF on stdin, and gets JSON back.
The child sets its own address-space limit (RLIMIT_AS) and CPU limit before it touches the file, gets an empty
environment (no credentials, no AWS keys), a scratch working directory, and is killed when the wall clock runs out.
Whatever goes wrong in it comes back as a `PdfRefused` code, never an exception carrying file text, and never a hang.

The result is JSON of the same dataclasses the in-process reader returns; the child's stderr is discarded so no
value from an invoice can reach a log.
"""

import json
import os
import subprocess
import sys
import tempfile
from dataclasses import asdict, fields

from .interface import ExtractedInvoice, ExtractedLine, Limits, PdfRefused, ReadResult

MAX_OUTPUT_BYTES = 8 * 1024 * 1024  # the child's answer is bounded too: a refused file is cheaper than a huge reply
GRACE_SECONDS = 2  # the child's own CPU limit fires first; the parent's kill is the backstop


def read_sandboxed(pdf: bytes, limits: Limits, hsn_pattern: str, *, max_memory_bytes: int) -> ReadResult:
    """The text-layer reader, run in a child. `hsn_pattern` is refdata `hsn.pattern` as text."""
    header = json.dumps({"limits": asdict(limits), "hsn": hsn_pattern, "memory": max_memory_bytes}).encode()
    with tempfile.TemporaryDirectory() as scratch:
        try:
            done = subprocess.run(
                [sys.executable, "-m", "app.modules.imports.pdf.worker"],
                input=header + b"\n" + pdf,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,  # nothing the child says about the file is kept
                timeout=limits.max_seconds + GRACE_SECONDS,
                cwd=scratch,
                # Only where to find the code, nothing else: no secret or cloud credential reaches the parser.
                env={"PYTHONPATH": os.pathsep.join(os.path.abspath(p) for p in sys.path if p), "PYTHONHASHSEED": "0"},
                check=False,
            )
        except subprocess.TimeoutExpired:  # subprocess.run has already killed the child
            raise PdfRefused("too_slow") from None
        except OSError:
            raise PdfRefused("unreadable") from None
    if len(done.stdout) > MAX_OUTPUT_BYTES:
        raise PdfRefused("too_complex")
    try:
        answer = json.loads(done.stdout)
    except ValueError:
        # No answer: the child died (killed for memory or CPU, or crashed). Never retry the same file blindly.
        raise PdfRefused("too_complex" if done.returncode else "unreadable") from None
    if not isinstance(answer, dict):
        raise PdfRefused("unreadable")
    if "refused" in answer:
        code = answer["refused"]
        raise PdfRefused(code if isinstance(code, str) and code in CODES else "unreadable")
    try:
        return _result(answer, limits)
    except (KeyError, TypeError, ValueError, AttributeError):
        raise PdfRefused("unreadable") from None  # an answer of the wrong shape is not a result


# The child's answer is untrusted (it ran on the file): every field is checked for type, length and count here.
CODES = frozenset({"not_a_pdf", "encrypted", "unreadable", "too_many_pages", "too_complex", "too_slow",
                   "too_many_documents", "ambiguous_split"})
MAX_TEXT = 100  # no extracted field is longer than this
MAX_UNCLEAR = 20


def _text(value) -> str | None:
    if value is not None and not (isinstance(value, str) and len(value) <= MAX_TEXT):
        raise ValueError("field")
    return value


def _ints(values, most: int, upto: int) -> tuple[int, ...]:
    if not isinstance(values, list) or len(values) > most:
        raise ValueError("ints")
    if any(isinstance(v, bool) or not isinstance(v, int) or not 1 <= v <= upto for v in values):
        raise ValueError("ints")
    return tuple(values)


def _names(values) -> frozenset[str]:
    if not isinstance(values, list) or len(values) > MAX_UNCLEAR:
        raise ValueError("names")
    return frozenset(_text(v) or "" for v in values)


def _exact(d, cls) -> dict:
    if not isinstance(d, dict) or set(d) != {f.name for f in fields(cls)}:
        raise ValueError("keys")
    return d


def _result(answer: dict, limits: Limits) -> ReadResult:
    def line(d):
        d = _exact(d, ExtractedLine)
        text = {k: _text(v) for k, v in d.items() if k not in ("page", "unclear")}
        return ExtractedLine(page=_ints([d["page"]], 1, limits.max_pages)[0], unclear=_names(d["unclear"]), **text)

    def invoice(d):
        d = _exact(d, ExtractedInvoice)
        if not isinstance(d["lines"], list) or len(d["lines"]) > limits.max_chars_per_page * limits.max_pages:
            raise ValueError("lines")
        text = {k: _text(v) for k, v in d.items() if k not in ("pages", "lines", "unclear")}
        return ExtractedInvoice(pages=_ints(d["pages"], limits.max_pages, limits.max_pages),
                                lines=tuple(line(x) for x in d["lines"]), unclear=_names(d["unclear"]), **text)

    if set(answer) != {"invoices", "unreadable_pages"} or not isinstance(answer["invoices"], list):
        raise ValueError("keys")
    if len(answer["invoices"]) > limits.max_documents:
        raise ValueError("documents")
    return ReadResult(tuple(invoice(d) for d in answer["invoices"]),
                      _ints(answer["unreadable_pages"], limits.max_pages, limits.max_pages))


def to_json(result: ReadResult) -> str:
    def plain(o):
        if isinstance(o, frozenset):
            return sorted(o)
        raise TypeError(type(o).__name__)

    return json.dumps(asdict(result), default=plain)
