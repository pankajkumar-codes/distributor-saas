import os
import sys
from pathlib import Path

# Unset PLATFORM_ENV fails closed (QA-DEF-004), so the suite names its environment, as CI does.
os.environ["PLATFORM_ENV"] = "test"

# A Postgres test that skips fails instead under CI=true or REQUIRE_PG=1 (tests/require_pg.py).
sys.path.append(str(Path(__file__).resolve().parents[3] / "tests"))
from require_pg import pytest_runtest_makereport  # noqa: E402, F401
