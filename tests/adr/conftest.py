import sys
from pathlib import Path

# A Postgres test that skips fails instead under CI=true or REQUIRE_PG=1 (tests/require_pg.py).
sys.path.append(str(Path(__file__).resolve().parents[1]))
from require_pg import pytest_runtest_makereport  # noqa: E402, F401
