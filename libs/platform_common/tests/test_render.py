"""platform_common.render (D-042): the worker's half of a render request."""

import importlib.util
import json
import uuid
from pathlib import Path

import pytest

from platform_common import render
from platform_common.queue import FakeQueue
from platform_common.storage import LocalObjectStore, set_store

_spec = importlib.util.spec_from_file_location(
    "renderer_inputs", Path(__file__).resolve().parents[3] / "renderer" / "renderer" / "inputs.py")
renderer_inputs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(renderer_inputs)


@pytest.fixture()
def wired(tmp_path):
    queue, store = FakeQueue(), LocalObjectStore(tmp_path)
    render.set_render_queue(queue)
    set_store(store)
    yield queue, store
    render.set_render_queue(None)
    set_store(None)


def test_a_request_writes_the_input_then_sends_only_its_key(wired):
    queue, store = wired
    b, r = uuid.uuid4(), uuid.uuid4()
    out = render.request(b, r, {"template": "invoice-draft", "seller": {"name": "शर्मा & Co <b>"}})
    key = f"render-input/b/{b}/{r}/input.json"
    assert queue.sent == [{"key": key}]
    assert json.loads(store.get_bytes(b, key)) == {"template": "invoice-draft", "v": 1,
                                                    "seller": {"name": "शर्मा & Co <b>"}}
    assert out == f"documents/b/{b}/{r}/document.pdf"
    assert render.is_rendered(b, r) is False
    store.put(b, out, b"%PDF", "application/pdf")
    assert render.is_rendered(b, r) is True


def test_the_renderer_derives_the_same_document_key():
    b, r = uuid.uuid4(), uuid.uuid4()
    assert renderer_inputs.document_key(render.input_key(b, r)) == render.document_key(b, r)


def test_a_repeated_request_is_the_same_input_and_key(wired):
    queue, store = wired
    b, r = uuid.uuid4(), uuid.uuid4()
    doc = {"template": "invoice-draft", "lines": [{"no": "1"}]}
    assert render.request(b, r, doc) == render.request(b, r, doc)
    assert queue.sent[0] == queue.sent[1]


def test_unknown_templates_and_oversized_inputs_are_refused_before_anything_is_written(wired):
    queue, store = wired
    b, r = uuid.uuid4(), uuid.uuid4()
    with pytest.raises(ValueError, match="template"):
        render.request(b, r, {"template": "other"})
    with pytest.raises(ValueError, match="over"):
        render.request(b, r, {"template": "invoice-draft", "x": "y" * render.MAX_INPUT_BYTES})
    assert queue.sent == [] and store.head(b, render.input_key(b, r)) is None


def test_no_queue_configured_is_an_error_not_a_silent_drop():
    render.set_render_queue(None)
    with pytest.raises(RuntimeError, match="no render queue"):
        render.get_render_queue()


def test_the_worker_and_the_renderer_share_one_input_size_limit():
    """The renderer can't import platform_common, so its copy is read as text."""
    import re

    handler = (Path(__file__).resolve().parents[3] / "renderer" / "renderer" / "handler.py").read_text()
    limit = re.search(r"^MAX_INPUT_BYTES = (.+?)\s*(#.*)?$", handler, re.M).group(1)
    assert eval(limit, {"__builtins__": {}}) == render.MAX_INPUT_BYTES  # noqa: S307 - a literal product
