"""The PDF renderer for the local demo only (#387). Never deployed anywhere.

In AWS the worker writes a render input under render-input/b/<business>/<render>/input.json
and sends its key to the `render` queue; the renderer Lambda turns it into
documents/b/<business>/<render>/document.pdf (D-042). Locally the app's render queue only
records the message (app/src/app/runtime.py) and the object store is a folder, the
demo's `build` volume. This process watches that folder instead of a queue and renders
each new input with the Lambda's own code, renderer.handler.render_one, from a task
directory built by scripts/build_renderer.py out of the same locks (same WeasyPrint,
pango, Noto fonts and templates). Nothing in the app changes: it sees the PDF appear,
or failed.json after the last try, exactly as it would in AWS.

    python demo/render_watch.py <objects dir>     # RENDERER_TASK names the task directory

It reads only render-input/b/<uuid>/<uuid>/input.json, and only once the store's
.meta.json beside it exists (LocalObjectStore writes the data first, then the meta, so a
half-written input is never read). It writes the PDF to a temporary name and renames it
into place, so the app never sees part of a PDF. An input whose PDF is newer is done; a
newer input (the same render asked again) is rendered again. After MAX_TRIES failures it
writes failed.json, the Lambda's last-try mark. Like the Lambda, it logs only error types,
never what an input holds.
"""

import io
import json
import logging
import os
import re
import sys
import time
from pathlib import Path

MAX_TRIES = 3  # the Lambda gets five, minutes apart; a local failure will not fix itself
POLL_SECONDS = 1.0
MAX_READ = 1024 * 1024 + 1  # one byte over renderer.handler.MAX_INPUT_BYTES
_UUID = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_INPUT = re.compile(rf"^render-input/b/{_UUID}/{_UUID}/input\.json$")
META = ".meta.json"  # platform_common.storage.LocalObjectStore keeps the content type here

log = logging.getLogger("render-watch")


class LocalS3:
    """The two S3 calls render_one makes, over the demo's object folder, in the same file
    layout LocalObjectStore uses (data file plus <name>.meta.json)."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if self.root.resolve() not in path.parents:
            raise ValueError("key outside the object folder")
        return path

    def get_object(self, Bucket, Key):  # noqa: N803, ARG002
        path = self._path(Key)
        with path.open("rb") as f:
            data = f.read(MAX_READ)  # render_one refuses anything over its 1 MB limit
        return {"Body": io.BytesIO(data), "ContentLength": path.stat().st_size}

    def put_object(self, Bucket, Key, Body, ContentType):  # noqa: N803, ARG002
        path = self._path(Key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_bytes(Body)
        # The meta first, then the data by rename: LocalObjectStore.head looks for the data file.
        path.with_name(path.name + META).write_text(json.dumps({"content_type": ContentType}))
        os.replace(tmp, path)


def pending(root: Path) -> list[tuple[str, int]]:
    """(key, input mtime) of each input fully written and not rendered since, oldest first."""
    found = []
    base = Path(root) / "render-input"
    if not base.is_dir():
        return found
    for path in base.glob("b/*/*/input.json"):
        key = path.relative_to(root).as_posix()
        if not _INPUT.match(key) or not path.with_name(path.name + META).is_file():
            continue
        out = Path(root) / "documents" / key.removeprefix("render-input/").removesuffix("input.json") / "document.pdf"
        try:
            if out.is_file() and out.stat().st_mtime_ns >= path.stat().st_mtime_ns:
                continue
            found.append((path.stat().st_mtime_ns, key))
        except FileNotFoundError:  # removed while looking: nothing to do
            continue
    return [(key, mtime) for mtime, key in sorted(found)]


def run_once(root: Path, render_one, record_failure, tries: dict) -> list[str]:
    """Renders what is pending. Returns the keys rendered. `tries` counts failures per input
    (key and mtime, so the same render asked again starts afresh) and is kept between calls
    by the caller."""
    s3, done = LocalS3(root), []
    for key, mtime in pending(root):
        attempt = (key, mtime)
        if tries.get(attempt, 0) >= MAX_TRIES:
            continue
        start = time.perf_counter()
        try:
            render_one(s3, "local", key)
        except Exception as e:  # noqa: BLE001
            tries[attempt] = tries.get(attempt, 0) + 1
            log.error("render failed (%d of %d): %s", tries[attempt], MAX_TRIES, type(e).__name__)
            if tries[attempt] >= MAX_TRIES:
                record_failure(s3, "local", key, "local")
            continue
        tries.pop(attempt, None)
        done.append(key)
        log.info("rendered a PDF in %d ms", (time.perf_counter() - start) * 1000)
    return done


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    logging.getLogger("weasyprint").setLevel(logging.WARNING)  # its per-step progress lines would bury ours
    root = Path(argv[1] if len(argv) > 1 else os.environ.get("LOCAL_OBJECTS_DIR", "build/objects"))
    task = os.environ.get("RENDERER_TASK", "/srv/renderer-task")
    sys.path.insert(0, task)
    from renderer import handler  # loads the bundled pango and fonts (renderer/boot.py)

    log.info("self-test: %s", handler.selftest())
    log.info("watching %s for render requests", root)
    tries: dict[tuple[str, int], int] = {}
    while True:
        try:
            run_once(root, handler.render_one, handler._record_failure, tries)  # noqa: SLF001
        except Exception as e:  # noqa: BLE001  keep watching; a bad pass must not stop the demo's renderer
            log.error("watch pass failed: %s", type(e).__name__)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
