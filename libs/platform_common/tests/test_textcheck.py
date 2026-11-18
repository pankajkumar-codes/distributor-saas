from typing import Annotated

from fastapi import FastAPI, Query
from fastapi.testclient import TestClient
from pydantic import BaseModel

from platform_common.textcheck import NoNul

app = FastAPI()


class Body(BaseModel):
    reason: Annotated[str | None, NoNul] = None


@app.get("/q")
def q(q: Annotated[str | None, NoNul, Query(max_length=100)] = None):
    return {"q": q}


@app.post("/b")
def b(body: Body):
    return body


client = TestClient(app)


def test_nul_in_a_query_parameter_is_422():
    assert client.get("/q", params={"q": "a\x00b"}).status_code == 422


def test_nul_in_a_body_field_is_422():
    assert client.post("/b", json={"reason": "a\x00b"}).status_code == 422


def test_ordinary_text_and_missing_values_pass():
    assert client.get("/q", params={"q": "tea"}).json() == {"q": "tea"}
    assert client.get("/q").json() == {"q": None}
    assert client.post("/b", json={}).status_code == 200
