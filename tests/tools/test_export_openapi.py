import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("export_openapi", Path(__file__).parents[2] / "scripts" / "export_openapi.py")
export_openapi = importlib.util.module_from_spec(spec)
spec.loader.exec_module(export_openapi)


def schemas(**props):
    return {"components": {"schemas": {"Invoice": {"properties": props}}}}


def test_money_named_numbers_are_refused():
    spec = schemas(total={"type": "number"}, cgst={"anyOf": [{"type": "number"}, {"type": "null"}]})
    assert len(export_openapi.money_numbers(spec)) == 2


def test_money_strings_and_non_money_numbers_pass():
    spec = schemas(total={"type": "string"}, quantity={"type": "number"}, page={"type": "integer"})
    assert export_openapi.money_numbers(spec) == []


def test_moneystr_ref_typed_as_number_is_refused():
    spec = schemas(due={"anyOf": [{"$ref": "#/components/schemas/MoneyStr"}, {"type": "number"}]})
    assert len(export_openapi.money_numbers(spec)) == 1

