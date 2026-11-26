"""The web app serves the product template as a static file (#425); it must stay the API's template, byte for byte."""

from pathlib import Path

from app.modules.catalog import product_import as imp

STATIC = Path(__file__).resolve().parents[6] / "web" / "public" / "products-template.csv"


def test_the_static_template_is_the_api_template():
    assert STATIC.read_bytes() == imp.template_csv()
