"""The local demo's renderer (demo/render_watch.py, #387): the same render_one as the
Lambda, fed from the demo's object folder instead of a queue. Runs against the built task
like the other renderer tests."""

import importlib.util
import json
import os
import uuid
from pathlib import Path

from test_render import _doc

WATCH = Path(__file__).resolve().parents[2] / "demo" / "render_watch.py"
_spec = importlib.util.spec_from_file_location("render_watch", WATCH)
render_watch = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(render_watch)


def _put(root: Path, key: str, data: bytes, content_type: str = "application/json", meta: bool = True) -> Path:
    """What platform_common.storage.LocalObjectStore._write leaves: the data, then its meta."""
    path = root / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    if meta:
        path.with_name(path.name + ".meta.json").write_text(json.dumps({"content_type": content_type}))
    return path


def _keys():
    b, r = uuid.uuid4(), uuid.uuid4()
    return f"render-input/b/{b}/{r}/input.json", f"documents/b/{b}/{r}"


def _run(root, tries=None):
    from renderer import handler

    return render_watch.run_once(root, handler.render_one, handler._record_failure, {} if tries is None else tries)


def test_an_input_becomes_a_whole_pdf_with_its_meta(tmp_path):
    key, out = _keys()
    _put(tmp_path, key, json.dumps(_doc()).encode())
    assert _run(tmp_path) == [key]
    pdf = tmp_path / out / "document.pdf"
    assert pdf.read_bytes().startswith(b"%PDF-")
    assert json.loads((tmp_path / out / "document.pdf.meta.json").read_text()) == {"content_type": "application/pdf"}
    assert not list((tmp_path / out).glob("*.tmp"))
    assert (tmp_path / key).exists()  # the input is left, as in AWS
    assert _run(tmp_path) == []  # done once; nothing to do on the next pass


def test_the_same_render_asked_again_is_drawn_again(tmp_path):
    key, out = _keys()
    path = _put(tmp_path, key, json.dumps(_doc()).encode())
    assert _run(tmp_path) == [key]
    pdf = tmp_path / out / "document.pdf"
    later = pdf.stat().st_mtime_ns + 1_000_000_000
    os.utime(path, ns=(later, later))
    assert _run(tmp_path) == [key]


def test_a_half_written_input_is_not_read(tmp_path):
    key, out = _keys()
    _put(tmp_path, key, b'{"templ', meta=False)  # the meta comes last, so the data may be partial
    assert _run(tmp_path) == []
    assert not (tmp_path / out).exists()


def test_a_broken_input_leaves_failed_json_after_three_tries_and_no_pdf(tmp_path):
    key, out = _keys()
    _put(tmp_path, key, json.dumps(_doc(template="no-such-template")).encode())
    tries = {}
    for n in range(1, 4):
        assert _run(tmp_path, tries) == []
        assert (tmp_path / out / "failed.json").exists() == (n == 3)
    assert not (tmp_path / out / "document.pdf").exists()
    assert json.loads((tmp_path / out / "failed.json").read_text()) == {"error_code": "render_failed"}
    assert _run(tmp_path, tries) == []  # gives up: no fourth try


def test_only_render_inputs_are_read(tmp_path):
    b, r = uuid.uuid4(), uuid.uuid4()
    for key in (f"render-input/b/{b}/{r}/other.json", f"uploads/b/{b}/{r}/input.json", f"render-input/b/x/{r}/input.json"):
        _put(tmp_path, key, json.dumps(_doc()).encode())
    assert _run(tmp_path) == []
    assert not (tmp_path / "documents").exists()


def test_a_key_cannot_leave_the_object_folder(tmp_path):
    s3 = render_watch.LocalS3(tmp_path)
    try:
        s3.put_object(Bucket="local", Key="../outside.pdf", Body=b"x", ContentType="application/pdf")
    except ValueError:
        pass
    else:
        raise AssertionError("wrote outside the object folder")
    assert not (tmp_path.parent / "outside.pdf").exists()
