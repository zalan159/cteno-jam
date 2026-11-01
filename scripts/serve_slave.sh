#!/usr/bin/env bash
# Start a dev server on a slave from the shipped working tree (used by e2e runs).
#   scripts/slave <host> -- bash scripts/serve_slave.sh [port] [data-dir]
set -euo pipefail
PORT="${1:-8765}"; DATA="${2:-$HOME/CtenoDev/jam/data-e2e}"
export PATH="$HOME/CtenoDev/jam/tools:$PATH" PYTHONPATH="$PWD/server" JAM_DATA_DIR="$DATA" JAM_PORT="$PORT"
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}" JAM_WHISPER_MODEL="${JAM_WHISPER_MODEL:-small}"
PIDF="$HOME/CtenoDev/jam/server-$PORT.pid"
if [ -f "$PIDF" ]; then kill "$(cat "$PIDF")" 2>/dev/null || true; sleep 1; fi
mkdir -p "$DATA"
setsid nohup venv/bin/python -m cteno_jam.app > "$DATA/server.log" 2>&1 &
echo $! > "$PIDF"
for i in $(seq 1 60); do curl -fsS "http://127.0.0.1:$PORT/api/info" >/dev/null 2>&1 && break; sleep 0.5; done
curl -fsS "http://127.0.0.1:$PORT/api/info"; echo
