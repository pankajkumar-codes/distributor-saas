"""The retention Lambda's loop (LLD-6 §6.1, D-041). The database side, including what may
be deleted and the disabled switch, is tests/isolation/test_retention.py."""

import itertools
import logging

import pytest

from app import retention


def _calls(monkeypatch, outputs):
    seen = []

    def fake(rule, dry_run):
        seen.append((rule, dry_run))
        out = outputs.pop(0)
        if isinstance(out, Exception):
            raise out
        return out

    monkeypatch.setattr(retention, "_call", fake)
    return seen


def _out(more, jobs=1, rate=None):
    return {"rule": "purge_operational", "counts": {"jobs": jobs, "rate_counters": rate}, "more": more}


def test_calls_again_while_more_and_sums_counts(monkeypatch):
    seen = _calls(monkeypatch, [_out(True, 5000), _out(True, 5000), _out(False, 7)])
    summary = retention.handler({"task": "purge_operational"}, None)
    assert seen == [("purge_operational", False)] * 3
    assert summary == {
        "purge_operational": {
            "dry_run": False,
            "calls": 3,
            "counts": {"jobs": 10007, "rate_counters": None},
            "more": False,
        }
    }


def test_stops_at_the_time_budget(monkeypatch):
    seen = _calls(monkeypatch, [_out(True)] * 10)
    ticks = itertools.count(0, 400)  # start, then 400 s per call
    summary = retention.run(clock=lambda: next(ticks), budget_seconds=600)
    assert len(seen) == 2
    assert summary["purge_operational"]["more"] is True


def test_disabled_rule_is_reported_and_not_repeated(monkeypatch):
    seen = _calls(
        monkeypatch,
        [{"rule": r, "skipped": "disabled"} for r in ("purge_operational", "purge_drafts", "purge_uploads")],
    )
    assert retention.handler({"task": "retention"}, None) == {
        "purge_operational": {"skipped": "disabled"},
        "purge_drafts": {"skipped": "disabled"},
        "purge_uploads": {"skipped": "disabled"},
    }
    assert [rule for rule, _ in seen] == ["purge_operational", "purge_drafts", "purge_uploads"]  # each once


def test_dry_run_is_one_call(monkeypatch):
    seen = _calls(monkeypatch, [_out(True), _out(True), _out(True)])
    retention.handler({"task": "retention", "dry_run": True}, None)
    assert seen == [("purge_operational", True), ("purge_drafts", True), ("purge_uploads", True)]  # one call per rule


def test_only_a_literal_true_means_dry_run(monkeypatch):
    seen = _calls(monkeypatch, [_out(False)])
    retention.handler({"task": "purge_operational", "dry_run": "yes"}, None)
    assert seen == [("purge_operational", False)]


def test_failure_logs_rule_and_class_only_and_raises(monkeypatch, caplog):
    _calls(monkeypatch, [RuntimeError("row for someone@example.test")])
    with caplog.at_level(logging.INFO), pytest.raises(RuntimeError):
        retention.handler({"task": "retention"}, None)
    assert "purge_operational" in caplog.text and "RuntimeError" in caplog.text
    assert "example.test" not in caplog.text


@pytest.mark.parametrize(
    "event", [{}, {"task": "sweep_outbox"}, {"task": "purge_gst_records"}, {"task": "retention.x"}]
)
def test_unknown_task_is_refused(monkeypatch, event):
    seen = _calls(monkeypatch, [])
    with pytest.raises(ValueError):
        retention.handler(event, None)
    assert seen == []


def test_imports_no_app_module():
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(retention))
    names = [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
    names += [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    assert not [n for n in names if n and n.startswith("app")]
