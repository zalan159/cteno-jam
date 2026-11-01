#!/usr/bin/env bash
# README screenshots, on a Mac test machine against a dev server with the demo songs seeded.
#   bash scripts/shots.sh <server-ip> [en|zh]
set -uo pipefail
HOST="$1"; LANG_="${2:-en}"; PORT=8765
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/node/bin:$PATH"
for p in $(lsof -t -iTCP:$PORT -sTCP:LISTEN 2>/dev/null); do ps -o command= -p "$p" | grep -q tcp_forward.py && kill "$p"; done
sleep 0.5
python3 scripts/tcp_forward.py $PORT "$HOST" $PORT & FWD=$!
trap 'kill $FWD 2>/dev/null' EXIT
sleep 1
cd e2e && JAM_URL=http://127.0.0.1:$PORT node shots.mjs ../docs/screenshots "$LANG_"
