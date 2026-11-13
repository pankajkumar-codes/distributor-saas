"""Creates the demo user and business through the API's own sign-up path (local demo only).

    python demo/seed.py http://api:8000        # inside the demo containers

Safe to run again: if the demo user can already sign in, it stops. Uses only the standard
library. The sign-up code is read from the local mail file, as a developer would read it.
Everything it creates is made up: a fictitious business with a synthetic GSTIN.
"""

import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_samples import DEMO_GSTIN  # noqa: E402

EMAIL = "demo@example.com"
PASSWORD = "seven lamps under a bridge"
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
    status, body = call(base, "POST", "/auth/signin", {"email": EMAIL, "password": PASSWORD})
    if status == 200:
        token = body["access_token"]
    else:
        need(*call(base, "POST", "/auth/signup", {"email": EMAIL}), (202,), "sign-up")
        status, body = call(base, "POST", "/auth/signup/verify",
                            {"email": EMAIL, "code": code_for(EMAIL), "password": PASSWORD})
        token = need(status, body, (200,), "verify")["access_token"]
    if need(*call(base, "GET", "/me/businesses", None, token), (200,), "list businesses")["businesses"]:
        print("demo business already exists")
        return
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


if __name__ == "__main__":
    main(sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://localhost:8000")
