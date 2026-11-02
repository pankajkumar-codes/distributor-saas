"""Product CSV import routes (LLD-3 §6.3, §7.1). S3-c1 serves the template; the upload,
complete, preview, confirm and discard routes come with S3-c2 on the job runner.

Mounted before the product routes, so /products/import-template isn't read as a product ID.
"""

from fastapi import APIRouter, Response
from fastapi import status as http

from .api_products import VIEW
from .product_import import template_csv

router = APIRouter(tags=["catalog"])


@router.get("/b/{business_id}/products/import-template", dependencies=VIEW,
            response_class=Response, responses={http.HTTP_200_OK: {"content": {"text/csv": {}}}})
def import_template():
    """The header row of the product file (§7.1). Column names are matched exactly."""
    return Response(template_csv(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="products-template.csv"'})
