#!/usr/bin/env bash
# Run the Playwright e2e suite on a Mac test machine against a dev server on another host.
#   scripts/e2e.sh <server-host-ip> [port] [playwright args...]
# The server is reached through a localhost forwarder: browsers only enable AudioWorklet (the
# pitch/tempo engine) in secure contexts, and http://127.0.0.1 counts as one. The forwarder
# lives as long as this script (macOS revokes LAN access of processes left behind by ssh).
set -uo pipefail
HOST="$1"; PORT="${2:-8765}"; shift; shift || true
cd "$(dirname "$0")/.."
# free the port if a stale forwarder (from an earlier, killed run) still holds it
for p in $(lsof -t -iTCP:$PORT -sTCP:LISTEN 2>/dev/null); do
  ps -o command= -p "$p" | grep -q tcp_forward.py && kill "$p"
done
sleep 0.5
python3 scripts/tcp_forward.py "$PORT" "$HOST" "$PORT" &
FWD=$!
trap 'kill $FWD 2>/dev/null' EXIT
for i in $(seq 1 20); do curl -fsS -m 2 -o /dev/null "http://127.0.0.1:$PORT/api/info" && break; sleep 0.3; done
cd e2e
EVID="${JAM_EVIDENCE:-../docs/evidence/e2e}"
mkdir -p "$EVID"
JAM_URL="http://127.0.0.1:$PORT" JAM_DEMO_DIR=../demo/source npx playwright test "$@" 2>&1 | tee "$EVID/playwright.log"
exit "${PIPESTATUS[0]}"
