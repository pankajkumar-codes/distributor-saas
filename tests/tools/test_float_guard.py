import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("float_guard", Path(__file__).parents[2] / "scripts" / "float_guard.py")
float_guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(float_guard)


def run(tmp_path, code):
    f = tmp_path / "pricing.py"
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


def test_guard_covers_money_module():
    assert any(p.name == "money.py" for p in float_guard.guarded_files())


def test_repo_is_clean_today():
    assert [p for f in float_guard.guarded_files() for p in float_guard.check(f)] == []
