"""A pytest hook shared by every suite: a test that skips because PostgreSQL isn't
configured fails instead under CI=true (GitHub Actions sets it) or REQUIRE_PG=1.

Locally, without PG_ADMIN_URL or PG_DSN, those tests still skip; in CI a missing
variable can no longer hide a whole Postgres suite behind a green run (#67).

Each suite's conftest imports `pytest_runtest_makereport` from here, which registers it.
"""

import os

import pytest

# The skip reasons the Postgres tests give (skipif marks and the isolation fixture).
_PG_VARIABLES = ("PG_ADMIN_URL", "PG_DSN")


def postgres_required() -> bool:
    return os.environ.get("REQUIRE_PG", "").lower() in ("1", "true") or os.environ.get("CI", "").lower() == "true"


def _pg_skip_reason(report) -> str | None:
    if not report.skipped or not isinstance(report.longrepr, tuple):
        return None
    reason = str(report.longrepr[2])
    return reason if any(v in reason for v in _PG_VARIABLES) else None


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    report = (yield).get_result()
    reason = _pg_skip_reason(report)
    if reason and postgres_required():
        report.outcome = "failed"
        report.longrepr = f"{reason}: PostgreSQL is required here (CI=true or REQUIRE_PG=1); set the variable"
