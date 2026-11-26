"""#470: a customer or product name is up to 200 characters, and the published API schema says the same 200 the server
enforces (it used to say 1000). The CGST Rules set no length for a name; 200 is the database column."""

import json
from pathlib import Path

import pytest

from app.modules.catalog import checks
from platform_common.errors import Invalid

OPENAPI = Path(__file__).resolve().parents[5] / "openapi.json"


def test_a_name_of_200_characters_is_accepted_and_201_is_refused_in_plain_words():
    assert checks.name("x" * 200) == "x" * 200
    with pytest.raises(Invalid) as e:
        checks.name("x" * 201)
    assert e.value.code == "name_invalid" and "200 characters" in e.value.message


@pytest.mark.parametrize("schema", ["CustomerIn", "CustomerPatch", "ProductIn", "ProductPatch"])
def test_the_published_schema_says_the_same_limit_the_server_enforces(schema):
    name = json.loads(OPENAPI.read_text())["components"]["schemas"][schema]["properties"]["name"]
    limits = [name.get("maxLength")] + [option.get("maxLength") for option in name.get("anyOf", []) if option.get("type") == "string"]
    assert checks.NAME_MAX == 200 and checks.NAME_MAX in limits and 1000 not in limits
