"""The API Lambda: every module's router, mounted under /api/v1."""

from fastapi import FastAPI
from mangum import Mangum

from app.modules.identity.api import router as identity_router

API_PREFIX = "/api/v1"

app = FastAPI(title="gst-app", root_path_in_servers=False)
app.include_router(identity_router, prefix=API_PREFIX)


@app.get(f"{API_PREFIX}/health")
def health():
    return {"status": "ok"}


handler = Mangum(app, lifespan="off")
