"""The objects bucket's lifecycle rules and IAM grants are per storage area (D-040), so
the Terraform must list exactly the areas platform_common.storage makes keys in. Read
as text: the lint job that runs tests/tools doesn't install platform_common."""

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_terraform_areas_match_storage_areas():
    code = (ROOT / "libs/platform_common/platform_common/storage.py").read_text()
    areas = ast.literal_eval(re.search(r"^AREAS = frozenset\((\{.*?\})\)", code, re.M).group(1))
    block = re.search(r"areas = \{(.*?)\n  \}", (ROOT / "infra/modules/storage/main.tf").read_text(), re.S).group(1)
    assert set(re.findall(r"^\s+([a-z]+)\s+=", block, re.M)) == areas
