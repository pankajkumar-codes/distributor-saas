#!/usr/bin/env bash
# The whole product on your own computer, for trying a milestone by hand. Needs only Docker.
# Mac and Linux twin of demo.ps1 (Windows); `make demo` calls this.
#   ./demo.sh            start (about 5 minutes the first time) and show sign-up codes here
#   ./demo.sh stop       stop it and forget everything it held
#   ./demo.sh codes      show the sign-up codes again (Ctrl+C leaves the demo running)
#   ./demo.sh status     what the demo server made of your uploaded files
#   ./demo.sh upload amazon demo/samples/demo-orders-good.csv
#   ./demo.sh tool <args>
# Made-up data only. See docs/LOCAL_DEMO.md.
set -uo pipefail
cd "$(dirname "$0")"
URL="http://localhost:5173"
dc() { docker compose -f docker-compose.demo.yml "$@"; }
die() { printf '\nThe demo could not start: %s\n%s\nMore help: docs/LOCAL_DEMO.md, section "If it does not open".\n' "$1" "$2" >&2; exit 1; }

check_docker() {
  command -v docker >/dev/null 2>&1 || die "Docker is not installed." "Install Docker Desktop (Mac) or Docker Engine (Linux), start it, then run this again."
  docker info >/dev/null 2>&1 || die "Docker is installed but not running." "Open Docker Desktop and wait until it says the engine is running, then run this again."
}

port_busy() {
  if command -v lsof >/dev/null 2>&1; then lsof -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
  elif command -v ss >/dev/null 2>&1; then ss -ltn "sport = :$1" 2>/dev/null | grep -q LISTEN
  else return 1; fi
}

wait_open() {
  echo "Waiting for the web page to answer..."
  for _ in $(seq 90); do
    if curl -fsS "$URL/api/v1/health" >/dev/null 2>&1; then return 0; fi
    sleep 2
  done
  die "The page did not answer within 3 minutes." "Run './demo.sh stop', then './demo.sh' again. If it repeats, look at: docker compose -f docker-compose.demo.yml logs api web"
}

case "${1:-start}" in
  start)
    check_docker
    echo "Starting the demo. The first time this downloads and builds things and can take 5 to 10 minutes."
    dc down -v --remove-orphans >/dev/null 2>&1   # every start is a clean one: sign-in lives in memory
    port_busy 5173 && die "Port 5173 is already used by another program on this computer." "Close the other program (often another 'npm run dev' or 'vite'), then run this again."
    dc up -d --build --wait api web codes || die "Docker could not build or start the demo." "Look at the lines above. Common causes: no internet while building, or Docker is out of disk space or memory."
    dc run --rm seed || die "Setting up the demo business failed." "Run './demo.sh stop' and try again."
    wait_open
    cat <<MSG

==================================================================
  The demo is ready.  Open this in your browser:

      $URL

  Ready-made account (a made-up business, Demo Traders):
      email:     demo@example.com
      password:  seven lamps under a bridge

  Or sign up as yourself: the 6-digit code appears right here.
  Sample files to upload are in the folder:  demo/samples
  Stop it with:  ./demo.sh stop      (Ctrl+C below only stops this code list)
==================================================================

MSG
    dc logs -f --no-log-prefix --tail 0 codes
    ;;
  stop) check_docker; dc down -v --remove-orphans && echo "The demo is stopped and its data is gone." ;;
  codes) check_docker; dc logs -f --no-log-prefix --tail 0 codes ;;
  status) check_docker; dc run --rm tool status ;;
  upload) check_docker; shift; dc run --rm tool upload "$@" ;;
  tool) check_docker; shift; dc run --rm tool "$@" ;;
  *) sed -n 2,11p "$0" ;;
esac
