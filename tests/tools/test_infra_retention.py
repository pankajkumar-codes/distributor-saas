"""The retention Lambda's Terraform (LLD-6 L6-5, D-041), read as text like
test_infra_areas: only the retention function logs in as app_retention, and its schedules
stay disabled until Pankaj's staging decision and a dry run there."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STACK = (ROOT / "infra" / "modules" / "stack" / "main.tf").read_text()


def _schedule(key):
    block = re.search(r"^\s*schedules = \{\n(.*?)\n\s*\}\n", STACK, re.M | re.S).group(1)
    m = re.search(rf"^\s*{re.escape(key)}\s*=\s*\{{(.*)\}}", block, re.M)
    assert m, f"schedule {key} not found"
    return m.group(1)


def test_purge_and_retention_schedules_are_disabled_and_target_the_retention_function():
    for key, task in (("purge", "purge_operational"), ("retention", "retention")):
        body = _schedule(key)
        assert re.search(r'target\s*=\s*"retention"', body), key
        assert re.search(rf'task\s*=\s*"{task}"', body), key
        assert re.search(r"enabled\s*=\s*false", body), f"{key} must stay disabled"


def test_only_the_retention_function_connects_as_app_retention():
    tf = "\n".join(p.read_text() for p in (ROOT / "infra").rglob("*.tf"))
    users = re.findall(r'db_user\s*=\s*"(app_retention)"', tf)
    assert len(users) == 1
    module = re.search(r'module "retention" \{(.*?)\n\}', STACK, re.S).group(1)
    assert re.search(r'db_user\s*=\s*"app_retention"', module)
    assert re.search(r'handler\s*=\s*"app.retention.handler"', module)
