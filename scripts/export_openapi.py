"""Export the API's OpenAPI document to app/openapi.json (LLD-0 §7 `openapi`, LLD-1 §11).

    python scripts/export_openapi.py          # rewrite app/openapi.json
    python scripts/export_openapi.py --check  # exit 1 if it is stale or has a money number (CI)

The web app generates its typed client from the committed file (web: `npm run gen:api`),
so a route change shows up as a diff in both. Money is a decimal string (MoneyStr), never
a JSON number: a schema property named like money, or using MoneyStr, may not be `number`.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "app" / "openapi.json"
MONEY_SUFFIXES = ("amount", "value", "tax", "total", "igst", "cgst", "sgst", "cess", "price")
# Properties named like money that are counts, each with the spec that fixes its name.
NOT_MONEY = {
    "Checklist.total",  # LLD-1 §10: how many setup items there are
}

sys.path[:0] = [str(ROOT / "app" / "src"), str(ROOT / "libs" / "platform_common")]


def render() -> str:
    from app.api import app

    return json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"


def money_numbers(spec: dict) -> list[str]:
    """Schema properties that hold money but are typed as a JSON number."""
    problems = []
    for schema_name, schema in spec.get("components", {}).get("schemas", {}).items():
        for prop, body in schema.get("properties", {}).items():
            types = [body.get("type")] + [s.get("type") for s in body.get("anyOf", [])]
            refs = [body.get("$ref", "")] + [s.get("$ref", "") for s in body.get("anyOf", [])]
            money = prop.lower().endswith(MONEY_SUFFIXES) or any(r.endswith("/MoneyStr") for r in refs)
            if money and f"{schema_name}.{prop}" not in NOT_MONEY and ("number" in types or "integer" in types):
                problems.append(f"{schema_name}.{prop}: money must be a decimal string, not a number")
    return problems


def main(argv: list[str]) -> int:
    text = render()
    problems = money_numbers(json.loads(text))
    if "--check" in argv:
        if not OUT.exists() or OUT.read_text() != text:
            problems.append(f"{OUT.relative_to(ROOT)} is stale: run python scripts/export_openapi.py")
    else:
        OUT.write_text(text)
    for p in problems:
        print(p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
