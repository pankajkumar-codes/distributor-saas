"""The demo's code list prints the ready-made account's two-step code and hides only its sign-up code (#447).

Runs demo/watch_codes.py on a temporary outbox; no Docker or database needed."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEMO = "demo@example.com"


def _watch(tmp_path, mails):
    outbox = tmp_path / "outbox.jsonl"
    outbox.write_text("")
    env = {**os.environ, "HIDE_EMAIL": DEMO}
    proc = subprocess.Popen([sys.executable, "-u", str(ROOT / "demo/watch_codes.py"), str(outbox)],
                            stdout=subprocess.PIPE, text=True, env=env)
    try:
        time.sleep(1)  # the watcher only prints mail that arrives after it starts
        with outbox.open("a") as f:
            for m in mails:
                f.write(json.dumps(m) + "\n")
        time.sleep(2)
    finally:
        proc.terminate()
    return proc.communicate(timeout=5)[0]


def test_the_demo_accounts_two_step_code_is_printed_and_its_signup_code_is_not(tmp_path):
    out = _watch(tmp_path, [
        {"template": "signup_code", "to": DEMO, "params": {"code": "111111"}},
        {"template": "demo_totp_code", "to": DEMO, "params": {"code": "222222"}},
        {"template": "reset_code", "to": DEMO, "params": {"code": "333333"}},
        {"template": "signup_code", "to": "me@example.com", "params": {"code": "444444"}},
    ])
    assert f"TWO-STEP CODE for {DEMO}:  222222" in out
    assert f"PASSWORD RESET CODE for {DEMO}:  333333" in out
    assert "SIGN-UP CODE for me@example.com:  444444" in out
    assert "111111" not in out


def test_codes_shows_the_ones_already_printed():
    # `./demo.sh codes` must show a code printed a moment ago, not only new ones.
    for name in ("demo.sh", "demo.ps1"):
        line = next(x for x in (ROOT / name).read_text().splitlines() if x.strip().startswith(("codes)", '"codes"')))
        assert "--tail 0" not in line and "--tail 50" in line, name
