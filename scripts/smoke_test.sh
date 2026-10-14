#!/usr/bin/env bash
# End-to-end check of the identity service, locally or on AWS.
#
# Local:  scripts/smoke_test.sh http://localhost:8000
#         (signs in with the X-Debug-User header, which only works when PLATFORM_ENV=local)
# AWS:    scripts/smoke_test.sh https://xxxx.execute-api.ap-south-1.amazonaws.com "$TOKEN_A" "$TOKEN_B"
#         (two Cognito access tokens for two different test users)
set -euo pipefail
BASE="${1:?base URL}"
TOKEN_A="${2:-}"
TOKEN_B="${3:-}"

auth() {
  # $1 = a or b
  if [ -n "$TOKEN_A" ]; then
    if [ "$1" = a ]; then echo "Authorization: Bearer $TOKEN_A"; else echo "Authorization: Bearer $TOKEN_B"; fi
  else
    echo "X-Debug-User: smoke-user-$1"
  fi
}

fail() { echo "FAIL: $*" >&2; exit 1; }
status() { curl -s -o /dev/null -w '%{http_code}' "$@"; }

echo "1. health"
[ "$(status "$BASE/identity/health")" = 200 ] || fail "health check"

echo "2. no login is rejected"
[ "$(status "$BASE/identity/tenants")" = 401 ] || fail "expected 401 without login"

echo "3. user A creates a tenant"
BODY=$(curl -s -X POST "$BASE/identity/tenants" -H "$(auth a)" -H 'content-type: application/json' -d '{"name":"Smoke Test Co"}')
TENANT=$(echo "$BODY" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])') || fail "create tenant: $BODY"
echo "   tenant $TENANT"

echo "4. user A can read it as owner"
ROLE=$(curl -s "$BASE/identity/tenants/$TENANT" -H "$(auth a)" | python3 -c 'import json,sys; print(json.load(sys.stdin)["role"])')
[ "$ROLE" = owner ] || fail "expected owner, got $ROLE"

if [ -n "$TOKEN_A" ] && [ -z "$TOKEN_B" ]; then
  echo "skipping isolation checks: pass a second user's token to run them"
else
  echo "5. user B cannot see user A's tenant (404, same as a missing one)"
  [ "$(status "$BASE/identity/tenants/$TENANT" -H "$(auth b)")" = 404 ] || fail "user B could see tenant"
  echo "6. user B cannot add themselves as a member"
  [ "$(status -X POST "$BASE/identity/tenants/$TENANT/members" -H "$(auth b)" -H 'content-type: application/json' -d '{"user_sub":"x","role":"owner"}')" = 404 ] || fail "user B could add a member"
fi

echo "7. audit log records the creation"
curl -s "$BASE/identity/tenants/$TENANT/audit" -H "$(auth a)" | grep -q tenant.created || fail "audit entry missing"

echo "ALL CHECKS PASSED"
