"""secrets.secret() prefers a plain `<NAME>` over `<NAME>_PARAM` (local runs and tests), so
Terraform must set only the `_PARAM` names: a plain key next to it would silently win
over Parameter Store. Read as text, like test_infra_areas."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KEYS = ("CODE_HMAC_KEY", "RATE_HMAC_KEY")


def test_terraform_sets_only_the_parameter_names_of_the_hmac_keys():
    tf = "\n".join(p.read_text() for p in (ROOT / "infra").rglob("*.tf"))
    for key in KEYS:
        assert re.search(rf"\b{key}_PARAM\s*=", tf), f"{key}_PARAM is not set by Terraform"
        assert not re.search(rf"\b{key}\s*=", tf), f"Terraform sets {key} directly; set only {key}_PARAM"
