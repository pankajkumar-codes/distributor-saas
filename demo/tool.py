"""Looks at what the demo server did with your uploads, and lets you decide a held row.
The web page (R1-M3) only shows each upload's status; the preview of rows, held rows and the
decision buttons come in later web slices, so this is how to see them today.

    python demo/tool.py status                          # every upload, its run and its held rows
    python demo/tool.py upload amazon demo/samples/demo-orders-good.csv   # same as the web page
    python demo/tool.py set-aside DEMO-2002 "Checked with the seller: not ours"
    python demo/tool.py discard <run id from status>    # throw a file's preview away
    python demo/tool.py confirm-check <run id>          # what stops a preview being confirmed (R1-M7)
    python demo/tool.py confirm <run id>                # confirm it into documents and a return (R1-M7)

Signs in as the demo user. Local demo only; standard library only; made-up data only.
"""

import json
import os
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import seed  # noqa: E402

BASE = os.environ.get("DEMO_API", "http://localhost:8000").rstrip("/")


def api(method, path, body=None, token=None):
    status, out = seed.call(BASE, method, path, body, token)
    return status, out


CACHE = Path(os.environ.get("DEMO_TOKEN_FILE", "/tmp/demo-token.json"))  # sign-in is rate limited; a token lasts 5 minutes


def login():
    try:
        saved = json.loads(CACHE.read_text())
        if time.time() - saved["at"] < 240 and saved["base"] == BASE:  # noqa: TID251 (a demo script, not business code)
            return saved["token"], saved["business"]
    except (OSError, ValueError, KeyError):
        pass
    status, body = api("POST", "/auth/signin", {"email": seed.EMAIL, "password": seed.PASSWORD})
    if status != 200:
        raise SystemExit("Could not sign in as the demo user (%s). Wait a minute, and if it keeps failing "
                         "the demo may still be starting or needs a reset." % status)
    token = body["access_token"]
    _, mine = api("GET", "/me/businesses", None, token)
    if not mine["businesses"]:
        raise SystemExit("The demo business is missing. Run the demo's seed step again.")
    business = mine["businesses"][0]["business_id"]
    try:
        now = time.time()  # noqa: TID251 (a demo script, not business code)
        CACHE.write_text(json.dumps({"at": now, "base": BASE, "token": token, "business": business}))
    except OSError:
        pass
    return token, business


def multipart(fields, name, content):
    boundary = uuid.uuid4().hex
    parts = []
    for k, v in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\n'
                 "Content-Type: application/octet-stream\r\n\r\n".encode() + content + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def held_rows(token, business, run_id):
    out = []
    _, page = api("GET", f"/b/{business}/runs/{run_id}/rows?status=held&limit=200", None, token)
    for row in page["rows"]:
        out.append(row)
    return out


def status():
    token, business = login()
    _, sections = api("GET", f"/b/{business}/upload-sections", None, token)
    print("Sections:")
    for s in sections["sections"]:
        extra = f", {s['held_rows']} rows held" if s["held_rows"] else ""
        print(f"  {s['section']:<20} {s['status']}{'' if s['enabled'] else ' (not open in this release)'}{extra}")
    _, ups = api("GET", f"/b/{business}/uploads?limit=50", None, token)
    print("\nUploads (newest first):")
    for u in ups["uploads"]:
        why = f"  <- {u['reject_message']}" if u["reject_reason"] else ""
        print(f"  {u['file_name']}  [{u['section']}]  {u['status']}{why}")
        for run_id in u["run_ids"]:
            _, run = api("GET", f"/b/{business}/runs/{run_id}", None, token)
            counts = {k: v for k, v in run["counts"].items() if v}
            print(f"      run {run_id}  {run['status']}  {counts}")
            for w in run.get("warnings", []):
                print(f"      note: {w.get('message', w.get('code'))}")
            if run["status"] != "staged":
                continue  # a discarded or used preview has nothing left to decide
            for row in held_rows(token, business, run_id):
                label = row.get("reason_label") or row.get("hold_reason")
                decided = row.get("resolution")
                state = f"decided: {decided['action']} ({decided['note']})" if decided else "needs a decision"
                print(f"      held row {row['values'].get('Order Id', row['row_number'])}: {label}; {state}")


def upload(section, path):
    token, business = login()
    p = Path(path)
    content = p.read_bytes()
    code, started = api("POST", f"/b/{business}/uploads", {"section": section, "file_name": p.name, "size_bytes": len(content)}, token)
    if code != 201:
        raise SystemExit(f"The server refused the upload ({code}): {started}")
    post = started["upload"]
    body, ctype = multipart(post["fields"], p.name, content)
    import urllib.request

    req = urllib.request.Request(BASE + post["url"], data=body, method="POST", headers={"Content-Type": ctype})
    urllib.request.urlopen(req, timeout=30).read()
    code, _ = api("POST", f"/b/{business}/uploads/{started['upload_id']}/complete", None, token)
    print("sent", p.name, "(%s)" % code, "- run `status` to see what the server made of it")


def find_row(token, business, order_id):
    _, ups = api("GET", f"/b/{business}/uploads?limit=50", None, token)
    for u in ups["uploads"]:
        for run_id in u["run_ids"]:
            if api("GET", f"/b/{business}/runs/{run_id}", None, token)[1]["status"] != "staged":
                continue  # a discarded or used preview has nothing left to decide
            for row in held_rows(token, business, run_id):
                if row["values"].get("Order Id") == order_id:
                    return row["row_id"]
    raise SystemExit(f"No held row for order {order_id}. Run `status` to see them.")


def set_aside(order_id, note):
    token, business = login()
    row_id = find_row(token, business, order_id)
    code, out = api("POST", f"/b/{business}/rows/{row_id}/resolve", {"action": "set_aside", "note": note}, token)
    print("done" if code == 200 else f"refused ({code}): {out['error']['message']}")


def discard(run_id):
    token, business = login()
    code, out = api("POST", f"/b/{business}/runs/{run_id}/discard", None, token)
    print("discarded" if code in (200, 204) else f"refused ({code}): {out}")


def confirm_check(run_id):
    token, business = login()
    code, out = api("GET", f"/b/{business}/runs/{run_id}/confirm-check", None, token)
    if code != 200:
        raise SystemExit(f"refused ({code}): {out}")
    print("can be confirmed" if out["can_confirm"] else "cannot be confirmed yet")
    print(f"  rows that would be used: {out['included']}, left out: {out['left_out']}")
    for b in out["blockers"]:
        rows = f" (rows {', '.join(map(str, b['rows']))})" if b["rows"] else ""
        ca = f" [waits on CA items: {', '.join(b['ca_items'])}]" if b["ca_items"] else ""
        print(f"  - {b['label']}{rows}{ca}")
    for n in out["notes"]:
        print(f"  note: {n['label']}")


def confirm(run_id):
    token, business = login()
    code, out = api("POST", f"/b/{business}/runs/{run_id}/confirm", {"changed": []}, token)
    print(f"confirmed: {out['documents']} documents, {out['lines']} lines" if code == 200
          else f"refused ({code}): {out['error']['message']}")


if __name__ == "__main__":
    cmd, args = (sys.argv[1] if len(sys.argv) > 1 else "status"), sys.argv[2:]
    if cmd == "status":
        status()
    elif cmd == "upload" and len(args) == 2:
        upload(*args)
    elif cmd == "set-aside" and len(args) == 2:
        set_aside(*args)
    elif cmd == "discard" and len(args) == 1:
        discard(*args)
    elif cmd == "confirm-check" and len(args) == 1:
        confirm_check(*args)
    elif cmd == "confirm" and len(args) == 1:
        confirm(*args)
    else:
        raise SystemExit(__doc__)
