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


def test_raw_upload_keep_days_in_refdata_equals_the_bucket_lifecycle():
    """The database marks an upload's raw file gone after imports.upload.keep_days; the bucket's
    `uploads/` lifecycle rule really deletes it after upload_retention_days. If they drift, the page
    offers a file that is gone, or says a file is gone while it is still kept (TD-18, R1-M3).
    Change both together, and the CA's answer on the period moves both."""
    refdata = (ROOT / "refdata" / "values" / "imports.yaml").read_text()
    m = re.search(r'- key: imports\.upload\.keep_days\n\s+value: "(\d+)"', refdata)
    assert m, "refdata imports.upload.keep_days not found"
    storage = (ROOT / "infra" / "modules" / "storage" / "main.tf").read_text()
    t = re.search(r'variable "upload_retention_days" \{.*?default\s*=\s*(\d+)', storage, re.S)
    assert t, "upload_retention_days default not found"
    assert m.group(1) == t.group(1), "refdata imports.upload.keep_days and Terraform upload_retention_days differ"
    # A tfvars example or env that overrides the variable would let them drift without this test seeing it.
    for tf in (ROOT / "infra").rglob("*"):
        if tf.is_file() and tf.suffix in (".tf", ".example", ".tfvars") and tf != ROOT / "infra" / "modules" / "storage" / "main.tf":
            assert "upload_retention_days" not in tf.read_text(), f"{tf} overrides upload_retention_days"
