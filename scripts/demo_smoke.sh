#!/usr/bin/env bash
# Runs the local demo the way a person does (./demo.sh) and checks what we claim about it: the page and /api
# answer through nginx, the demo account signs in, restarting only the API keeps accounts and sessions, and a
# stuck database does not stop the API from answering. Used by the `demo-smoke` CI job (needs Docker); also
# runnable by hand: ./scripts/demo_smoke.sh. Made-up data only. Prints "PASS" lines, exits non-zero on the first miss.
set -uo pipefail
cd "$(dirname "$0")/.."
URL=http://localhost:5173
DC="docker compose -f docker-compose.demo.yml"
EMAIL=demo@example.com
PASSWORD='Seven-Lamps-42!'
JAR=$(mktemp)
mkdir -p build
START_LOG=build/demo-start.log

pass() { echo "PASS: $*"; }
fail() { echo "FAIL: $*"; exit 1; }

# One request: prints "<status> <seconds>", body to $BODY.
BODY=$(mktemp)
req() { curl -sS -m "${TIMEOUT:-20}" -o "$BODY" -w '%{http_code} %{time_total}' "$@" || echo "000 0"; }
status() { echo "${1%% *}"; }
secs() { echo "${1##* }"; }
under() { python3 -c "import sys; sys.exit(0 if float('$1') < float('$2') else 1)"; }
json() { python3 -c "import json,sys; print(json.load(open('$BODY'))$1)"; }
signin() {
  local r
  r=$(req -c "$JAR" -b "$JAR" -X POST "$URL/api/v1/auth/signin" -H 'Content-Type: application/json' -H "Origin: $URL" \
    -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}")
  # One active session per user: a sign-in while the earlier one is live is asked first. Answer yes, as the page does.
  if [ "$(status "$r")" = 200 ] && grep -q '"session_active"' "$BODY"; then
    req -c "$JAR" -b "$JAR" -X POST "$URL/api/v1/auth/session/replace" -H "Origin: $URL" -H "Authorization: Bearer $(json "['access_token']")"
  else
    echo "$r"
  fi
}

cleanup() { kill "${START_PID:-0}" 2>/dev/null; $DC unpause db >/dev/null 2>&1; }
trap cleanup EXIT

# 1. Start it exactly as a person does. ./demo.sh ends by following the code list, so run it in the background
#    and wait for its "ready" box.
echo "Starting ./demo.sh (the first build takes a few minutes)..."
./demo.sh > "$START_LOG" 2>&1 &
START_PID=$!
for _ in $(seq 240); do
  grep -q "The demo is ready" "$START_LOG" 2>/dev/null && break
  kill -0 "$START_PID" 2>/dev/null || { cat "$START_LOG"; fail "./demo.sh stopped before it was ready"; }
  sleep 3
done
grep -q "The demo is ready" "$START_LOG" || { cat "$START_LOG"; fail "./demo.sh was not ready after 12 minutes"; }
pass "./demo.sh reached its ready box"

# 2. Everything the compose file says is healthy is healthy, and nothing has restarted on its own.
$DC ps
for s in api web db renderer; do
  [ "$($DC ps --status running -q "$s" | wc -l)" = 1 ] || fail "$s is not running"
done
pass "db, api, web and renderer are running"
# The PDF renderer (#387) loaded its bundled pango and fonts and drew its self-test page.
# Read the logs into a variable before grep -q: with pipefail, grep -q closing the pipe early can SIGPIPE `logs` and
# fail the check although the line is there (#490).
for _ in $(seq 30); do rlog=$($DC logs renderer 2>&1); grep -q "watching /srv/build/objects" <<<"$rlog" && break; sleep 2; done
rlog=$($DC logs renderer 2>&1)
grep -q "self-test: {'pages': 1" <<<"$rlog" || { printf '%s\n' "$rlog"; fail "the renderer did not pass its self-test"; }
pass "the renderer drew its self-test page and is watching for previews"

# 3. The page and the API through nginx.
for n in 1 2 3; do
  r=$(req "$URL/api/v1/health")
  [ "$(status "$r")" = 200 ] || fail "health through nginx: $r"
  under "$(secs "$r")" 1 || fail "health through nginx took $(secs "$r") s"
done
pass "/api/v1/health through nginx: 200, under 1 s, three times"
# "/" is the Kartaa landing page for a visitor, and the app for someone with the signed-in hint cookie (demo/nginx.conf).
r=$(req "$URL/"); [ "$(status "$r")" = 200 ] && grep -q 'href="/signin"' "$BODY" && ! grep -q 'id="root"' "$BODY" || fail "a visitor at / did not get the landing page: $r"
curl -sSI -m 20 "$URL/" | grep -qi '^cache-control: no-cache' || fail "/ should be sent with Cache-Control: no-cache"
r=$(req -H 'Cookie: kartaa_in=1' "$URL/"); [ "$(status "$r")" = 200 ] && grep -q 'id="root"' "$BODY" || fail "a signed-in visitor at / did not get the app: $r"
r=$(req "$URL/signin"); [ "$(status "$r")" = 200 ] && grep -q 'id="root"' "$BODY" || fail "/signin did not load the app: $r"
r=$(req "$URL/assets/does-not-exist.js"); [ "$(status "$r")" = 404 ] || fail "a missing asset should be 404, got: $r"
curl -sSI -m 20 "$URL/b/x/invoices/new" | grep -qi '^cache-control: no-cache' || fail "an app page should be sent with Cache-Control: no-cache, so a new build shows on reload"
pass "/ is the landing page for a visitor and the app when signed in; /signin loads; a missing asset is a 404"
req -H 'Cookie: kartaa_in=1' "$URL/" >/dev/null
ASSET=$(grep -o '/assets/[^"]*\.js' "$BODY" | head -1)
[ -n "$ASSET" ] || fail "no script found in the page"
r=$(req "$URL$ASSET"); [ "$(status "$r")" = 200 ] || fail "the app's script did not load: $r"
curl -sSI -m 20 "$URL$ASSET" | grep -qi '^cache-control: .*immutable' || fail "the app's hashed script should be sent as immutable"
pass "the app's script loads"

# 4. The demo account signs in, and /me answers.
r=$(signin); [ "$(status "$r")" = 200 ] || fail "demo sign-in: $r $(cat "$BODY")"
TOKEN=$(json "['access_token']")
r=$(req -H "Authorization: Bearer $TOKEN" "$URL/api/v1/me"); [ "$(status "$r")" = 200 ] || fail "/me: $r"
r=$(req -H "Authorization: Bearer $TOKEN" "$URL/api/v1/me/businesses"); [ "$(status "$r")" = 200 ] || fail "/me/businesses: $r"
grep -q "Demo Traders" "$BODY" || fail "the demo business is not listed"
pass "demo sign-in, /me and the demo business"

# 5. Restart only the API: the same token, the refresh cookie and the password all still work.
$DC restart api >/dev/null 2>&1 || fail "docker compose restart api failed"
for _ in $(seq 60); do [ "$(status "$(req "$URL/api/v1/health")")" = 200 ] && break; sleep 2; done
r=$(req "$URL/api/v1/health"); [ "$(status "$r")" = 200 ] || fail "the API did not come back after a restart: $r"
r=$(req -H "Authorization: Bearer $TOKEN" "$URL/api/v1/me"); [ "$(status "$r")" = 200 ] || fail "after an API restart, the old token no longer works: $r"
r=$(req -c "$JAR" -b "$JAR" -X POST "$URL/api/v1/auth/refresh" -H "Origin: $URL"); [ "$(status "$r")" = 200 ] || fail "after an API restart, refresh failed: $r"
r=$(signin); [ "$(status "$r")" = 200 ] || fail "after an API restart, sign-in failed: $r"
pass "after restarting only the API: old token, refresh cookie and sign-in all still work"

# 6. A stuck database must not stop the API answering. Pausing the db container freezes Postgres with its
#    connections still open, like a database that has stopped answering.
TOKEN=$(json "['access_token']")
$DC pause db >/dev/null || fail "could not pause db"
( TIMEOUT=60 req -H "Authorization: Bearer $TOKEN" "$URL/api/v1/me" > build/stuck-me.txt ) &
STUCK=$!
sleep 2
worst=0
for n in 1 2 3 4; do
  r=$(TIMEOUT=5 req "$URL/api/v1/health")
  [ "$(status "$r")" = 200 ] || { $DC unpause db >/dev/null 2>&1; fail "while the database was frozen, /health said: $r"; }
  under "$(secs "$r")" 1 || { $DC unpause db >/dev/null 2>&1; fail "while the database was frozen, /health took $(secs "$r") s"; }
  sleep 1
done
pass "while the database is frozen and a signed-in request waits on it, /health still answers in under 1 s"
$DC unpause db >/dev/null || fail "could not unpause db"
wait "$STUCK"
for _ in $(seq 30); do
  r=$(req -H "Authorization: Bearer $TOKEN" "$URL/api/v1/me"); [ "$(status "$r")" = 200 ] && break; sleep 2
done
[ "$(status "$r")" = 200 ] || fail "after the database came back, /me said: $r"
r=$(signin); [ "$(status "$r")" = 200 ] || fail "after the database came back, sign-in said: $r"
pass "after the database comes back, /me and sign-in work again"

# 7. `./demo.sh check` runs and finds everything answering.
./demo.sh check > build/demo-check.txt 2>&1 || { cat build/demo-check.txt; fail "./demo.sh check failed"; }
grep -q "inside the web container, page and API through it: OK" build/demo-check.txt || { cat build/demo-check.txt; fail "./demo.sh check did not find the web container answering"; }
pass "./demo.sh check"

echo "All demo checks passed."
