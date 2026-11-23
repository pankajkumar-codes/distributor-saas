"""Creates the demo user and business through the API's own sign-up path (local demo only), then
its ready-made customers and products (demo/demo_data.py) through the same API a person uses.

    python demo/seed.py http://api:8000        # inside the demo containers

Safe to run again: it signs in if the demo user exists, keeps the business it already has, and adds
only the customers (matched by name) and products (matched by code) that are missing. Uses only the standard
library. The sign-up code is read from the local mail file, as a developer would read it.
Everything it creates is made up: a fictitious business with a synthetic GSTIN.
"""

import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from demo_data import CUSTOMERS, PRODUCTS  # noqa: E402
from make_samples import DEMO_GSTIN  # noqa: E402

EMAIL = "demo@example.com"
PASSWORD = "Seven-Lamps-42!"
OUTBOX = Path(os.environ.get("MAIL_OUTBOX", "/srv/build/mail/outbox.jsonl"))
ORIGIN = "http://localhost:5173"  # the API only answers sign-in cookies for its own web origin


def call(base, method, path, body=None, token=None):
    headers = {"Content-Type": "application/json", "Origin": ORIGIN, "Idempotency-Key": uuid.uuid4().hex}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(base + "/api/v1" + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            text = r.read().decode()
            return r.status, (json.loads(text) if text else None)
    except urllib.error.HTTPError as e:
        text = e.read().decode()
        return e.code, (json.loads(text) if text else None)


def code_for(email):
    for _ in range(60):
        if OUTBOX.exists():
            mine = [json.loads(line) for line in OUTBOX.read_text().splitlines() if line.strip()]
            mine = [m for m in mine if m["to"] == email and m["template"] == "signup_code"]
            if mine:
                return mine[-1]["params"]["code"]
        time.sleep(0.5)
    raise SystemExit("seed: no sign-up code arrived in the local mail file")


def need(status, body, ok, what):
    if status not in ok:
        raise SystemExit(f"seed: {what} failed with {status}: {body}")
    return body


def today_ist():
    from zoneinfo import ZoneInfo

    return dt.datetime.now(ZoneInfo("Asia/Kolkata")).date()  # noqa: TID251 (a demo script, not business code)


def quarter_start(today):
    return today.replace(month=3 * ((today.month - 1) // 3) + 1, day=1)


def main(base):
    token = None
    try:
        token = _seed(base)
    finally:
        # One active session per user: a seed that stayed signed in would make the owner's own first sign-in
        # ask "One session is already active". Sign out whatever was opened (sign-out never refuses).
        if token:
            call(base, "POST", "/auth/signout", None, token)


def _seed(base):
    status, body = call(base, "POST", "/auth/signin", {"email": EMAIL, "password": PASSWORD})
    if status == 200 and "step" not in body:
        token = body["access_token"]
    else:
        need(*call(base, "POST", "/auth/signup", {"email": EMAIL, "password": PASSWORD}), (202,), "sign-up")
        status, body = call(base, "POST", "/auth/signup/verify",
                            {"email": EMAIL, "code": code_for(EMAIL), "password": PASSWORD})
        token = need(status, body, (200,), "verify")["access_token"]
    businesses = need(*call(base, "GET", "/me/businesses", None, token), (200,), "list businesses")["businesses"]
    if businesses:
        print("demo business already exists")
        _catalog(base, businesses[0]["business_id"], token)
        return token
    business = need(
        *call(base, "POST", "/b", {
            "registration": {"kind": "gstin", "gstin": DEMO_GSTIN},
            "legal_name": "Demo Traders (made up)",
            "trade_name": "Demo Traders",
            "address": {"line1": "1 Demo Road", "city": "Kolkata", "pin": "700001", "state_code": "19"},
            "turnover_band": "up_to_threshold",
            "einvoice_history": "no",
        }, token),
        (201,), "create business",
    )["business_id"]
    need(*call(base, "PUT", f"/b/{business}/channels",
               {"amazon": True, "flipkart": True, "meesho": True, "own_invoices": True}, token), (200,), "channels")
    need(*call(base, "POST", f"/b/{business}/filing-profile/frequency",
               {"frequency": "monthly", "effective_from": quarter_start(today_ist()).isoformat()}, token),
         (200, 201), "filing frequency")
    print("demo business created")
    _catalog(base, business, token)
    return token


def _catalog(base, business, token):
    """Adds the demo customers and products the business doesn't have yet (archived ones count as had)."""
    added = 0
    for c in CUSTOMERS:
        q = urllib.parse.quote(c["name"][:100])
        found = need(*call(base, "GET", f"/b/{business}/customers?status=all&limit=200&q={q}", None, token),
                     (200,), "list customers")
        if not any(x["name"] == c["name"] for x in found["items"]):
            need(*call(base, "POST", f"/b/{business}/customers", c, token), (201,), f"customer {c['name']}")
            added += 1
    for p in PRODUCTS:
        found = need(*call(base, "GET", f"/b/{business}/products?status=all&limit=200&q={p['code']}", None, token),
                     (200,), "list products")
        if not any(x["code"] == p["code"] for x in found["items"]):
            need(*call(base, "POST", f"/b/{business}/products", p, token), (201,), f"product {p['code']}")
            added += 1
    print(f"demo customers and products: {added} added")


if __name__ == "__main__":
    main(sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://localhost:8000")
