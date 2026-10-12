"""reports: registers, stock and settlement reconciliation, CSV/Excel exports.
Read-only against the other services' schemas."""

from fastapi import FastAPI
from mangum import Mangum

app = FastAPI(title="reports")


@app.get("/reports/health")
def health():
    return {"status": "ok"}


handler = Mangum(app, lifespan="off")
