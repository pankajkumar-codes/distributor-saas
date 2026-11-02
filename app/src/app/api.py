"""The API Lambda: every module's router, mounted under /api/v1."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from mangum import Mangum

from app import runtime
from app.home.api import router as home_router
from app.modules.business.api import router as business_router
from app.modules.catalog.api_customers import router as customers_router
from app.modules.catalog.api_products import router as products_router
from app.modules.identity.api import router as identity_router
from app.modules.identity.api_auth import router as auth_router
from app.modules.identity.api_me import router as me_router
from app.modules.identity.api_team import router as team_router
from app.modules.identity.interface import resolve_principal
from app.modules.identity.providers import auth_provider
from app.modules.refdata.api import router as refdata_router
from platform_common.auth import debug_env
from platform_common.errors import install_error_handlers
from platform_common.jobs_api import router as jobs_router
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
install_error_handlers(app)  # Deny -> 404, AppError -> its status, anything else -> 500 (LLD-0 §3.2)
app.include_router(identity_router, prefix=API_PREFIX)
app.include_router(auth_router, prefix=API_PREFIX)
app.include_router(me_router, prefix=API_PREFIX)
app.include_router(team_router, prefix=API_PREFIX)
app.include_router(business_router, prefix=API_PREFIX)
app.include_router(home_router, prefix=API_PREFIX)
app.include_router(products_router, prefix=API_PREFIX)
app.include_router(customers_router, prefix=API_PREFIX)
app.include_router(refdata_router, prefix=API_PREFIX)
app.include_router(jobs_router, prefix=API_PREFIX)  # platform routes (LLD-0 §3.7)
if debug_env():
    from app.dev_routes import router as dev_router

    app.include_router(dev_router, prefix=API_PREFIX)
# business_uow and me_uow check every caller through identity (LLD-1 §6).
set_principal_resolver(resolve_principal)
runtime.configure()  # the jobs queue and object store for this environment


@app.get(f"{API_PREFIX}/health")
def health():
    return {"status": "ok"}


handler = Mangum(app, lifespan="off")
