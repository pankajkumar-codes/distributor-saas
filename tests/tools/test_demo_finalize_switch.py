"""Finalize ships off, and the only way to turn it on outside a test is the demo flag (D-010, D-044, CA-1).

Read as text and YAML, like test_infra_secrets: no database needed."""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
KEY = "sales.finalize.enabled"


def test_the_shipped_default_is_off():
    rows = yaml.safe_load((ROOT / "refdata/values/sales.yaml").read_text())
    values = [r["value"] for r in rows if r["key"] == KEY]
    assert values == ["false"], "finalize must ship off until the CA confirms the numbering scope"


def test_the_demo_turns_it_on_only_with_the_flag():
    sh = (ROOT / "demo.sh").read_text()
    assert sh.count("enable-finalize.sql") == 1
    block = re.search(r'if \[ "\$FINALIZE" = 1 \]; then(.*?)\n    fi', sh, re.S)
    assert block and "enable-finalize.sql" in block.group(1), "the SQL must run only inside the --finalize branch"
    assert "FINALIZE=0" in sh
    ps = (ROOT / "demo.ps1").read_text()
    assert re.search(r"if \(\$Finalize\) \{[^}]*enable-finalize\.sql", ps, re.S)
    compose = (ROOT / "docker-compose.demo.yml").read_text()
    assert KEY not in compose and "FINALIZE" not in compose.upper()


def test_no_deployed_config_can_turn_it_on():
    scanned = [*(ROOT / "infra").rglob("*"), *(ROOT / ".github").rglob("*"), *(ROOT / "refdata").rglob("*.yaml")]
    hits = [
        str(p.relative_to(ROOT))
        for p in scanned
        if p.is_file() and p.suffix in {".tf", ".tfvars", ".yml", ".yaml", ".json", ".sh"} and "finalize_enabled" in p.read_text().lower()
    ]
    assert not hits, hits
    for p in (ROOT / "infra").rglob("*"):
        if p.is_file() and p.suffix in {".tf", ".tfvars"}:
            assert "sales.finalize" not in p.read_text(), p
    assert (ROOT / "demo" / "enable-finalize.sql").is_file()
