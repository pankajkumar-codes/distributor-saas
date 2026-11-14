"""The child process of `sandbox.read_sandboxed`: limits first, then read stdin, parse, answer on stdout (R1-M6 S2a).

Run as `python -m app.modules.imports.pdf.worker`. It never opens a file or a socket of its own, never logs, and
answers with one JSON object: the result, or {"refused": code}.
"""

import json
import re
import sys

from .interface import Limits, PdfRefused


def _limit(memory: int, cpu: int) -> None:
    try:
        import resource
    except ImportError:  # not a platform with rlimits (the parent's wall clock is then the only guard)
        return
    for name, value in (("RLIMIT_AS", memory), ("RLIMIT_CPU", cpu), ("RLIMIT_FSIZE", 0), ("RLIMIT_CORE", 0)):
        if hasattr(resource, name):
            try:
                resource.setrlimit(getattr(resource, name), (value, value))
            except (ValueError, OSError):
                pass


def main() -> int:
    raw = sys.stdin.buffer.read()
    header, _, pdf = raw.partition(b"\n")
    del raw
    try:
        spec = json.loads(header)
        limits = Limits(**spec["limits"])
        # Imported before the limit is set would be cheaper to start; after, the import itself is inside it.
        _limit(int(spec["memory"]), limits.max_seconds + 1)
        from .sandbox import to_json
        from .text_reader import TextLayerReader

        out = to_json(TextLayerReader(re.compile(spec["hsn"])).read(pdf, limits))
    except PdfRefused as refused:
        out = json.dumps({"refused": refused.code})
    except MemoryError:
        out = json.dumps({"refused": "too_complex"})
    except BaseException:  # noqa: BLE001 - nothing from the file may leave except a code
        out = json.dumps({"refused": "unreadable"})
    sys.stdout.write(out)
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
