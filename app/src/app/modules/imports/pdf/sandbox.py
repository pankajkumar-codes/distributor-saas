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
from dataclasses import asdict

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
                capture_output=True,
                timeout=limits.max_seconds + GRACE_SECONDS,
                cwd=scratch,
                # Only where to find the code, nothing else: no secret or cloud credential reaches the parser.
                env={"PYTHONPATH": os.pathsep.join(p for p in sys.path if p), "PYTHONHASHSEED": "0"},
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
    if "refused" in answer:
        raise PdfRefused(str(answer["refused"]))
    return _result(answer)


def _result(answer: dict) -> ReadResult:
    def line(d):
        return ExtractedLine(**{**d, "unclear": frozenset(d["unclear"])})

    def invoice(d):
        return ExtractedInvoice(**{**d, "pages": tuple(d["pages"]), "lines": tuple(line(x) for x in d["lines"]),
                                   "unclear": frozenset(d["unclear"])})

    return ReadResult(tuple(invoice(d) for d in answer["invoices"]), tuple(answer["unreadable_pages"]))


def to_json(result: ReadResult) -> str:
    def plain(o):
        if isinstance(o, frozenset):
            return sorted(o)
        raise TypeError(type(o).__name__)

    return json.dumps(asdict(result), default=plain)
