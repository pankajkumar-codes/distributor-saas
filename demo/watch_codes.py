"""Prints each new code the local app "emails", so the person trying the demo can read it
in the terminal. Local demo only: the app writes mail to a file instead of sending it.

    python demo/watch_codes.py /srv/build/mail/outbox.jsonl
"""

import json
import os
import sys
import time
from pathlib import Path

path = Path(sys.argv[1] if len(sys.argv) > 1 else "build/mail/outbox.jsonl")
hide = os.environ.get("HIDE_EMAIL", "")  # only this address's SIGN-UP code is hidden
pos = path.stat().st_size if path.exists() else 0  # only mail that arrives from now on
print("Watching for sign-up, password-reset and two-step codes and team invitation links. They will appear here.", flush=True)
while True:
    if path.exists() and path.stat().st_size > pos:
        with path.open("rb") as f:
            f.seek(pos)
            chunk = f.read()
        done = chunk.rfind(b"\n") + 1  # only whole lines
        pos += done
        for line in chunk[:done].decode().splitlines():
            try:
                m = json.loads(line)
            except ValueError:
                continue
            if hide and m.get("to") == hide and m.get("template") == "signup_code":
                continue  # the seed's own sign-up code for the ready-made account; its two-step code still shows (#447)
            params = m.get("params", {})
            if m["template"] == "invitation" and params.get("link"):
                # The demo has no real email, so the accept link is printed here (never on the Team page).
                print(f"\n  INVITATION for {m['to']} ({params.get('inviter_name', '')} invites them to {params.get('business_name', '')} "
                      f"as {params.get('role_label', '')}).\n  Open this link in a browser where you are signed out, "
                      f"or signed in as {m['to']}:\n\n      {params['link']}\n", flush=True)
                continue
            code = params.get("code")
            what = {"signup_code": "SIGN-UP CODE", "reset_code": "PASSWORD RESET CODE", "demo_totp_code": "TWO-STEP CODE"}.get(m["template"], m["template"])
            print(f"\n  {what} for {m['to']}:  {code}\n" if code else f"\n  Email '{m['template']}' to {m['to']}\n", flush=True)
    time.sleep(0.5)
