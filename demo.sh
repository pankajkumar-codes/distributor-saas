#!/usr/bin/env bash
# The whole product on your own computer, for trying a milestone by hand. Needs only Docker.
# Mac and Linux twin of demo.ps1 (Windows); `make demo` calls this.
#   ./demo.sh            start (about 5 minutes the first time) and show sign-up codes here
#   ./demo.sh --finalize start with finalize switched on, so an invoice can be finalized (numbers are PRACTICE only)
#   ./demo.sh stop       stop it and forget everything it held
#   ./demo.sh codes      show the sign-up codes again (Ctrl+C leaves the demo running)
#   ./demo.sh check      quick health check: is each piece up, and does the page answer
#   ./demo.sh logs       save what every piece printed into demo-logs.txt (send that file if something fails)
#   UVICORN_LOG_LEVEL=debug ./demo.sh    start with a more detailed API log
#   ./demo.sh status     what the demo server made of your uploaded files
#   ./demo.sh upload amazon demo/samples/demo-orders-good.csv
#   ./demo.sh tool <args>
# Run ./demo.sh again after every git pull: it rebuilds from the files you have and starts clean.
# If something fails, run ./demo.sh logs and send demo-logs.txt. Made-up data only. See docs/LOCAL_DEMO.md.
set -uo pipefail
cd "$(dirname "$0")"
URL="http://localhost:5173"
dc() { docker compose -f docker-compose.demo.yml "$@"; }
die() { printf '\nThe demo could not start: %s\n%s\nMore help: docs/LOCAL_DEMO.md, section "If it does not open".\n' "$1" "$2" >&2; exit 1; }

check_docker() {
  command -v docker >/dev/null 2>&1 || die "Docker is not installed." "Install Docker Desktop (Mac) or Docker Engine (Linux), start it, then run this again."
  docker info >/dev/null 2>&1 || die "Docker is installed but not running." "Open Docker Desktop and wait until it says the engine is running, then run this again."
}

warn_slow_disk() {
  case "$PWD" in
    /mnt/[a-z]/*) printf '\nNote: this folder is on the Windows disk (%s), which is slow from WSL. It works, but builds are slow and\nanything that waits on the disk can be late. Faster: clone the project inside Ubuntu (cd ~ && git clone ...) and run it from there.\n\n' "$PWD" ;;
  esac
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

FINALIZE=0
for arg in "$@"; do [ "$arg" = "--finalize" ] && FINALIZE=1; done
cmd="${1:-start}"
[ "$cmd" = "--finalize" ] && cmd=start

case "$cmd" in
  start)
    check_docker
    warn_slow_disk
    echo "Starting the demo. The first time this downloads and builds things and can take 5 to 10 minutes."
    dc down -v --remove-orphans >/dev/null 2>&1   # every start is a clean one: sign-in lives in memory
    port_busy 5173 && die "Port 5173 is already used by another program on this computer." "Close the other program (often another 'npm run dev' or 'vite'), then run this again."
    dc up -d --build --wait api web codes renderer || die "Docker could not build or start the demo." "Look at the lines above. Common causes: no internet while building, or Docker is out of disk space or memory."
    dc run --rm seed || die "Setting up the demo business failed." "Run './demo.sh stop' and try again."
    wait_open
    if [ "$FINALIZE" = 1 ]; then
      dc exec -T db psql -U postgres -d saas -v ON_ERROR_STOP=1 < demo/enable-finalize.sql >/dev/null \
        || die "Switching finalize on failed." "Run './demo.sh stop' and start again without --finalize, or send demo-logs.txt."
      printf '\nFinalize is ON in this demo. Numbers it gives are PRACTICE only, not real invoice numbers.\nThey stay off everywhere else until the CA confirms the numbering scope.\n'
    fi
    cat <<MSG

==================================================================
  The demo is ready.  Open this in your browser:

      $URL

  Ready-made account (a made-up business, Demo Traders):
      email:     demo@example.com
      password:  Seven-Lamps-42!

  Or sign up as yourself: the 6-digit code appears right here.
  Sample files to upload are in the folder:  demo/samples
  Stop it with:  ./demo.sh stop      (Ctrl+C below only stops this code list)
==================================================================

MSG
    dc logs -f --no-log-prefix --tail 0 codes
    ;;
  stop) check_docker; dc down -v --remove-orphans && echo "The demo is stopped and its data is gone." ;;
  codes) check_docker; dc logs -f --no-log-prefix --tail 50 codes ;;   # the codes already printed, then new ones
  check)
    check_docker
    dc ps
    echo
    for n in 1 2 3; do
      curl -sS -m 5 -o /dev/null -w "from this computer, page and API through it: HTTP %{http_code} in %{time_total}s\n" "$URL/api/v1/health" || echo "from this computer: no answer within 5 s"
    done
    # Same question asked from inside the web container, which skips Docker's port forwarding. If this answers
    # but the lines above do not, the problem is between your computer and Docker, not in the demo itself.
    dc exec -T web wget -q -T 5 -O /dev/null http://127.0.0.1:5173/api/v1/health && echo "inside the web container, page and API through it: OK" || echo "inside the web container: no answer within 5 s"
    docker stats --no-stream --format "{{.Name}}: cpu {{.CPUPerc}}, memory {{.MemUsage}}" $(dc ps -q) 2>/dev/null
    dc exec -T api python -c "import urllib.request as u; print('inside the api container: HTTP', u.urlopen('http://localhost:8000/api/v1/health', timeout=5).status)" || echo "inside the api container: no answer within 5 s"
    ;;
  logs)
    check_docker
    { date -u; echo "folder: $PWD"; echo; dc ps -a; echo; dc logs --no-color --timestamps; } > demo-logs.txt 2>&1
    echo "Saved demo-logs.txt (made-up data only). Send that file, plus a screenshot of the browser error."
    ;;
  status) check_docker; dc run --rm tool status ;;
  upload) check_docker; shift; dc run --rm tool upload "$@" ;;
  tool) check_docker; shift; dc run --rm tool "$@" ;;
  *) sed -n 2,11p "$0" ;;
esac
