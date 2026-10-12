"""imports: marketplace CSV/Excel uploads, staging rows, validation and
de-duplication. Nothing reaches stock or money until a person confirms the preview.

Parsers wait on sample reports from Amazon, Flipkart and Meesho (open question 2).
"""

from fastapi import FastAPI
from mangum import Mangum

app = FastAPI(title="imports")


@app.get("/imports/health")
def health():
    return {"status": "ok"}


handler = Mangum(app, lifespan="off")
