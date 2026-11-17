"""The four files for the one test upload to the portal (scripts/make_portal_test_files.py)."""

import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[6] / "scripts" / "make_portal_test_files.py"


def load():
    spec = importlib.util.spec_from_file_location("make_portal_test_files", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_four_files_differ_only_as_the_test_plan_says(tmp_path, monkeypatch):
    mod = load()
    monkeypatch.setattr("sys.argv", ["x", "--gstin", "19AAAAA0000A1Z5", "--period", "112026", "--out", str(tmp_path)])
    mod.main()
    t = {p.stem.split("_")[0]: json.loads(p.read_bytes()) for p in tmp_path.glob("*.json")}
    assert set(t) == {"T1", "T2", "T3", "T4"}
    assert "chksum" not in json.dumps(t["T1"]) and json.dumps(t["T2"]).count("chksum") == 2
    assert "flag" in json.dumps(t["T1"]) and "flag" not in json.dumps(t["T3"]) and "cflag" not in json.dumps(t["T3"])
    assert "hsn" not in t["T1"] and "hsn" in t["T4"]
    assert t["T1"]["b2b"][0]["inv"][0]["inum"] == "TEST/0001"  # never a number a real invoice could have
    assert t["T1"]["fp"] == "112026" and t["T1"]["gstin"] == "19AAAAA0000A1Z5"


def test_a_bad_gstin_or_period_is_refused(tmp_path, monkeypatch):
    import pytest

    mod = load()
    for gstin, period in (("short", "112026"), ("19AAAAA0000A1Z5", "132026")):
        monkeypatch.setattr("sys.argv", ["x", "--gstin", gstin, "--period", period, "--out", str(tmp_path)])
        with pytest.raises(SystemExit):
            mod.main()
