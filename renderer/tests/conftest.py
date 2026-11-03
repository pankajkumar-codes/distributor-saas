"""The renderer's tests run against a built task directory, so they exercise the real
bundled pango, fonts and WeasyPrint: unzip build/renderer-x86_64.zip and point
RENDERER_TASK at it (the CI job `renderer` does this). Without it they are skipped,
because nothing else has WeasyPrint's native libraries."""

import os
import sys

import pytest

TASK = os.environ.get("RENDERER_TASK")
if TASK:
    sys.path.insert(0, os.path.abspath(TASK))


def pytest_collection_modifyitems(config, items):  # noqa: ARG001
    if not TASK:
        skip = pytest.mark.skip(reason="set RENDERER_TASK to an unpacked renderer zip")
        for item in items:
            item.add_marker(skip)
