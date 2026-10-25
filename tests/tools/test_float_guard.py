import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("float_guard", Path(__file__).parents[2] / "scripts" / "float_guard.py")
float_guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(float_guard)


def run(tmp_path, code):
    f = tmp_path / "anything.py"
    f.write_text(code)
    return float_guard.check(f)


def test_flags_float_literal_call_and_annotation(tmp_path):
    problems = run(tmp_path, "def f(x: float):\n    return float(x) * 1.18\n")
    assert len(problems) == 3


def test_allows_decimal_strings_and_isinstance_rejection(tmp_path):
    code = (
        "from decimal import Decimal\n"
        "RATE = Decimal('0.18')\n"
        "def f(v):\n"
        "    if isinstance(v, float) or isinstance(v, (bool, float)):\n"
        "        raise ValueError\n"
        "    return Decimal(v) * RATE\n"
    )
    assert run(tmp_path, code) == []


def test_opt_out_comment(tmp_path):
    assert run(tmp_path, "RATIO = 0.5  # float-ok: chart scaling only, not money\n") == []


def test_opt_out_needs_a_reason(tmp_path):
    assert len(run(tmp_path, "RATIO = 0.5  # float-ok:\n")) == 1


def test_guard_covers_every_app_and_lib_module_but_not_tests():
    files = [p.relative_to(float_guard.ROOT) for p in float_guard.guarded_files()]
    assert any(p.name == "money.py" for p in files)
    # Modules whose names say nothing about money are guarded too.
    assert any(p.parts[0] == "app" and "money" not in p.stem for p in files)
    assert any(p.parts[:4] == ("app", "src", "app", "modules") for p in files)
    assert any(p.parts[0] == "migrator" for p in files)
    assert not any("tests" in p.parts for p in files)


def test_repo_is_clean_today():
    assert [p for f in float_guard.guarded_files() for p in float_guard.check(f)] == []
