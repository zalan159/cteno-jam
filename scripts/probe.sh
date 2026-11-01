#!/usr/bin/env bash
# dev: run e2e/probe.mjs against a remote dev server through a localhost forwarder (Mac test machine)
#   bash scripts/probe.sh <server-ip> <hash-path> [engines...]
set -uo pipefail
HOST="$1"; HASH="$2"; shift 2
ENGINES="${*:-webkit chromium}"
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/node/bin:$PATH"
PORT=8765
# free the port if a stale forwarder (from an earlier, killed run) still holds it
for p in $(lsof -t -iTCP:$PORT -sTCP:LISTEN 2>/dev/null); do
  ps -o command= -p "$p" | grep -q tcp_forward.py && kill "$p"
done
sleep 0.5
python3 scripts/tcp_forward.py $PORT "$HOST" $PORT & FWD=$!
trap 'kill $FWD 2>/dev/null' EXIT
sleep 1
cd e2e
for e in $ENGINES; do
  echo "== $e"
  node probe.mjs "http://127.0.0.1:$PORT/#$HASH" "$e" 2>&1 | grep -v '^console'
done
