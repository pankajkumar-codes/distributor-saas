"""The audit log's CSV files get their own storage area with a one-day lifecycle rule (LLD-2
§7, EM on #108), so they don't share `exports/` with files kept longer (LLD-5, LLD-6)."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STORAGE = (ROOT / "infra" / "modules" / "storage" / "main.tf").read_text()
PLATFORM = (ROOT / "libs" / "platform_common" / "platform_common" / "storage.py").read_text()
EXPORT = (ROOT / "app" / "src" / "app" / "modules" / "identity" / "audit_export.py").read_text()


def test_audit_exports_expire_after_a_day_and_their_old_versions_a_day_later():
    assert re.search(r'^\s*"audit-exports"\s*=\s*\{\s*expire_days\s*=\s*1,\s*noncurrent_days\s*=\s*1\s*\}', STORAGE, re.M)


def test_the_app_writes_audit_exports_only_to_that_area():
    assert '"audit-exports"' in re.search(r"^AREAS = frozenset\(\{(.*)\}\)$", PLATFORM, re.M).group(1)
    assert re.search(r'^AREA = "audit-exports"', EXPORT, re.M)
    assert '"exports"' not in EXPORT
