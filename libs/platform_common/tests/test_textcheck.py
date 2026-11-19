from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from platform_common.textcheck import RejectNul, has_nul

app = FastAPI()
app.add_middleware(RejectNul)


class Body(BaseModel):
    reason: str | None = None
    items: list[dict] = []


@app.get("/q")
def q(q: str | None = None):
    return {"q": q}


@app.post("/b")
def b(body: Body):
    return body


client = TestClient(app)


def test_nul_in_a_query_parameter_is_422():
    for raw in ("a%00b", "a%00", "%00"):
        r = client.get(f"/q?q={raw}")
        assert r.status_code == 422 and r.json()["error"]["code"] == "text_invalid", raw


def test_nul_anywhere_in_a_json_body_is_422_even_nested():
    for body in ({"reason": "a\x00b"}, {"items": [{"x": {"y": ["\x00"]}}]}, {"items": [{"a\x00": 1}]}):
        r = client.post("/b", json=body)
        assert r.status_code == 422 and r.json()["error"]["code"] == "text_invalid", body


def test_ordinary_text_missing_values_and_non_json_pass_through():
    assert client.get("/q?q=tea").json() == {"q": "tea"}
    assert client.get("/q").json() == {"q": None}
    assert client.post("/b", json={"reason": "ok \\u0000 literal backslash text"}).status_code == 200
    assert client.post("/b", content=b"not json", headers={"content-type": "application/json"}).status_code == 422  # the route's own answer
    assert not has_nul({"a": ["b", 1, None]})


def test_nul_in_a_url_encoded_form_is_422():
    for raw in (b"a=b%00c", b"a%00=b", b"x=1&y=%00"):
        r = client.post("/b", content=raw, headers={"content-type": "application/x-www-form-urlencoded"})
        assert r.status_code == 422 and r.json()["error"]["code"] == "text_invalid", raw
    ok = client.post("/b", content=b"a=b+c%20d", headers={"content-type": "application/x-www-form-urlencoded"})
    assert ok.json().get("error", {}).get("code") != "text_invalid"  # the route's own answer, not the guard's


def test_json_over_one_megabyte_is_still_checked():
    big = "x" * 1_200_000
    r = client.post("/b", json={"reason": big + "\x00"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "text_invalid"
    assert client.post("/b", json={"reason": big}).status_code == 200


def test_a_plus_json_media_type_is_checked_like_json():
    for media in ("application/vnd.api+json", "application/merge-patch+json", "application/json; charset=utf-8"):
        r = client.post("/b", content=b'{"reason": "a\\u0000b"}', headers={"content-type": media})
        assert r.status_code == 422 and r.json()["error"]["code"] == "text_invalid", media
        ok = client.post("/b", content=b'{"reason": "fine"}', headers={"content-type": media})
        assert ok.status_code == 200, media
