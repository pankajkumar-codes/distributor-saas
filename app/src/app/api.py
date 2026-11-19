"""The API Lambda: every module's router, mounted under /api/v1."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from mangum import Mangum

from app import runtime
from app.home.api import router as home_router
from app.modules.business.api import router as business_router
from app.modules.catalog.api_customers import router as customers_router
from app.modules.catalog.api_imports import router as product_imports_router
from app.modules.catalog.api_products import router as products_router
from app.modules.catalog.api_stock import router as stock_router
from app.modules.imports.api import router as uploads_router
from app.modules.imports.api_purchases import router as purchases_router
from app.modules.imports.readers import register_readers
from app.modules.sales.api import router as drafts_router
from app.modules.identity.api import router as identity_router
from app.modules.identity.api_auth import router as auth_router
from app.modules.identity.api_me import router as me_router
from app.modules.identity.api_grants import router as grants_router
from app.modules.identity.api_support import router as support_router
from app.modules.identity.api_team import router as team_router
from app.modules.identity.interface import resolve_principal
from app.modules.identity.providers import auth_provider
from app.modules.filing.api import router as filing_router
from app.modules.filing.api_period_files import router as period_files_router
from app.modules.filing.api_period_gate import router as period_gate_router
from app.modules.filing.api_worksheet import router as worksheet_router
from app.modules.refdata.api import router as refdata_router
from platform_common.auth import debug_env
from platform_common.errors import install_error_handlers
from platform_common.jobs_api import router as jobs_router
from platform_common.textcheck import RejectNul
from platform_common.uow import set_principal_resolver

API_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Local only (uvicorn): build the fake IdP now, so its keys verify bearer tokens from
    # the first request, not only after some /auth call has built it. Lambda runs with
    # lifespan off and has no fake IdP.
    if debug_env():
        auth_provider()
    yield


app = FastAPI(title="gst-app", root_path_in_servers=False, lifespan=lifespan)
app.add_middleware(RejectNul)  # no NUL character in any query string or JSON body (#281)
install_error_handlers(app)  # Deny -> 404, AppError -> its status, anything else -> 500 (LLD-0 §3.2)
app.include_router(identity_router, prefix=API_PREFIX)
app.include_router(auth_router, prefix=API_PREFIX)
app.include_router(me_router, prefix=API_PREFIX)
app.include_router(support_router, prefix=API_PREFIX)
app.include_router(grants_router, prefix=API_PREFIX)
app.include_router(team_router, prefix=API_PREFIX)
app.include_router(business_router, prefix=API_PREFIX)
app.include_router(home_router, prefix=API_PREFIX)
app.include_router(product_imports_router, prefix=API_PREFIX)  # before products: /products/import-template
app.include_router(products_router, prefix=API_PREFIX)
app.include_router(stock_router, prefix=API_PREFIX)
app.include_router(customers_router, prefix=API_PREFIX)
app.include_router(drafts_router, prefix=API_PREFIX)
app.include_router(filing_router, prefix=API_PREFIX)
app.include_router(worksheet_router, prefix=API_PREFIX)
app.include_router(period_files_router, prefix=API_PREFIX)
app.include_router(period_gate_router, prefix=API_PREFIX)
app.include_router(uploads_router, prefix=API_PREFIX)
app.include_router(purchases_router, prefix=API_PREFIX)
app.include_router(refdata_router, prefix=API_PREFIX)
app.include_router(jobs_router, prefix=API_PREFIX)  # platform routes (LLD-0 §3.7)
if debug_env():
    from app.dev_routes import router as dev_router

    app.include_router(dev_router, prefix=API_PREFIX)

    from app.demo_readers import register_demo_readers

    register_demo_readers()  # only when DEMO_READERS=1: the local demo's invented layout
# business_uow and me_uow check every caller through identity (LLD-1 §6).
set_principal_resolver(resolve_principal)
register_readers()  # Amazon, Flipkart, Meesho (R1-M4) and the own-invoice template (R1-M5)
runtime.configure()  # the jobs queue and object store for this environment


@app.get(f"{API_PREFIX}/health")
async def health():  # async: answered on the event loop, so it never waits for a busy or stuck worker thread
    return {"status": "ok"}


# The handlers take these two headers as optional so a missing one gets the API's own error
# (for example idempotency_key_required) instead of a generic 422. They are
# mandatory for callers, so the contract says required (#282).
_REQUIRED_HEADERS = {"Idempotency-Key", "If-Match"}
# Genuinely optional today: the first band for a year takes no If-Match, and a purchase draft's
# confirm and discard work without a key (a key only makes a retry safe).
_STAYS_OPTIONAL = {
    ("put", "/api/v1/b/{business_id}/turnover-bands/{fy}", "If-Match"),
    ("post", "/api/v1/b/{business_id}/purchase-drafts/{draft_id}/confirm", "Idempotency-Key"),
    ("post", "/api/v1/b/{business_id}/purchase-drafts/{draft_id}/discard", "Idempotency-Key"),
}


def _openapi_with_required_headers() -> dict:
    if app.openapi_schema:
        return app.openapi_schema
    schema = FastAPI.openapi(app)
    canonical = {h.lower(): h for h in _REQUIRED_HEADERS}
    for path, operations in schema["paths"].items():
        for method, operation in operations.items():
            for parameter in operation.get("parameters", []):
                # A handler declared as `idempotency_key: str | None = Header(None)` is named in
                # lowercase in the schema, so the match ignores case.
                name = canonical.get(parameter["name"].lower())
                if parameter.get("in") == "header" and name:
                    parameter["required"] = (method, path, name) not in _STAYS_OPTIONAL
    return schema


app.openapi = _openapi_with_required_headers  # type: ignore[method-assign]


handler = Mangum(app, lifespan="off")
