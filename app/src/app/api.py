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
from platform_common.uow import set_principal_resolver

API_PREFIX = "/api/v1"

# Set on every response by the app itself, so they hold on the API Gateway endpoint (the API is not behind
# CloudFront, D-094) and locally. An answer that already carries one keeps it. HSTS is harmless over plain
# http (browsers ignore it there). The API returns JSON and files, never a page, so the CSP forbids everything.
SECURITY_HEADERS = (
    (b"x-content-type-options", b"nosniff"),
    (b"strict-transport-security", b"max-age=31536000"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
)
API_CSP = (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'; base-uri 'none'")


class SecurityHeaders:
    """Pure ASGI middleware: add the headers above to every HTTP response, even an error or a 404."""

    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.inner(scope, receive, send)
        csp = scope.get("path", "").startswith(API_PREFIX)  # the dev-only /docs page needs its own scripts

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                have = {name.lower() for name, _ in headers}
                for pair in (*SECURITY_HEADERS, *((API_CSP,) if csp else ())):
                    if pair[0] not in have:
                        headers.append(pair)
                message = {**message, "headers": headers}
            await send(message)

        await self.inner(scope, receive, send_with_headers)


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Local only (uvicorn): build the fake IdP now, so its keys verify bearer tokens from
    # the first request, not only after some /auth call has built it. Lambda runs with
    # lifespan off and has no fake IdP.
    if debug_env():
        auth_provider()
    yield


app = FastAPI(title="gst-app", root_path_in_servers=False, lifespan=lifespan)
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


# The whole app is wrapped, not added with add_middleware: Starlette answers an unhandled exception (the 500) in
# a layer outside every added middleware, which would leave that response without the headers. Lambda and
# uvicorn run `asgi`; `app` stays for the OpenAPI export and the tests of single routes.
asgi = SecurityHeaders(app)
handler = Mangum(asgi, lifespan="off")
