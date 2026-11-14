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
hide = os.environ.get("HIDE_EMAIL", "")
pos = path.stat().st_size if path.exists() else 0  # only mail that arrives from now on
print("Watching for sign-up and reset codes. They will appear here.", flush=True)
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
            if m.get("to") == hide:
                continue
            code = m.get("params", {}).get("code")
            what = {"signup_code": "SIGN-UP CODE", "reset_code": "PASSWORD RESET CODE"}.get(m["template"], m["template"])
            print(f"\n  {what} for {m['to']}:  {code}\n" if code else f"\n  Email '{m['template']}' to {m['to']}\n", flush=True)
    time.sleep(0.5)
