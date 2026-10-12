"""commerce: catalog, suppliers, purchases, stock ledger, customers, wholesale
invoices and payments. These stay in one service because finalizing an invoice,
moving its stock and recording its payment must commit in one database transaction.

Business endpoints wait on blocking decisions D-009 to D-013 (docs/DECISIONS.md).
"""

from fastapi import FastAPI
from mangum import Mangum

app = FastAPI(title="commerce")


@app.get("/commerce/health")
def health():
    return {"status": "ok"}


handler = Mangum(app, lifespan="off")
