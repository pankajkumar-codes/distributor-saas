"""One password policy in three places (D-061): refdata, the server check and the Cognito user pool.

The pool's own policy is the last line, so it must never be stricter or looser than what the screens show. Terraform is
written only (never applied from here), so this reads its text. A change to either side fails this test until both agree.
"""

import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[6]
TERRAFORM = REPO / "infra" / "modules" / "auth" / "main.tf"
REFDATA = REPO / "refdata" / "values" / "auth.yaml"
# The symbols a Cognito user pool accepts (AWS documents this fixed list); ours must be a subset of it.
COGNITO_SYMBOLS = set("^$*.[]{}()?\"!@#%&/\\,><':;|_~`=+-")
COGNITO_MAX_LENGTH = 256


def _refdata() -> dict:
    rows = yaml.safe_load(REFDATA.read_text())
    return {r["key"]: r["value"] for r in rows if r["key"].startswith("auth.password_")}


def _pool() -> dict:
    block = re.search(r"password_policy\s*\{(.*?)\n\s*\}", TERRAFORM.read_text(), re.S)
    assert block, "no password_policy block in the auth module"
    return dict(re.findall(r"^\s*(\w+)\s*=\s*(\w+)", block.group(1), re.M))


def test_the_cognito_pool_asks_for_what_refdata_asks_for():
    ref, pool = _refdata(), _pool()
    assert int(pool["minimum_length"]) == int(ref["auth.password_min_length"])
    for terraform_key, refdata_key in [
        ("require_uppercase", "auth.password_require_upper"),
        ("require_lowercase", "auth.password_require_lower"),
        ("require_numbers", "auth.password_require_digit"),
        ("require_symbols", "auth.password_require_special"),
    ]:
        assert pool[terraform_key] == str(ref[refdata_key]).lower(), terraform_key


def test_refdata_never_allows_what_the_pool_cannot_take():
    ref = _refdata()
    assert int(ref["auth.password_max_length"]) <= COGNITO_MAX_LENGTH
    assert set(ref["auth.password_specials"]) <= COGNITO_SYMBOLS
