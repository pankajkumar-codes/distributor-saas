"""The API Lambda: every module's router, mounted under /api/v1."""

from fastapi import FastAPI
from mangum import Mangum

from app.modules.catalog.api_products import router as products_router
from app.modules.identity.api import router as identity_router
from app.modules.identity.api_auth import router as auth_router
from app.modules.identity.api_me import router as me_router
from app.modules.identity.api_team import router as team_router
from app.modules.identity.interface import resolve_principal
from platform_common.errors import install_error_handlers
from platform_common.uow import set_principal_resolver

API_PREFIX = "/api/v1"

app = FastAPI(title="gst-app", root_path_in_servers=False)
install_error_handlers(app)  # Deny -> 404, AppError -> its status, anything else -> 500 (LLD-0 §3.2)
app.include_router(identity_router, prefix=API_PREFIX)
app.include_router(auth_router, prefix=API_PREFIX)
app.include_router(me_router, prefix=API_PREFIX)
app.include_router(team_router, prefix=API_PREFIX)
app.include_router(products_router, prefix=API_PREFIX)
# business_uow and me_uow check every caller through identity (LLD-1 §6).
set_principal_resolver(resolve_principal)


@app.get(f"{API_PREFIX}/health")
def health():
    return {"status": "ok"}


handler = Mangum(app, lifespan="off")
