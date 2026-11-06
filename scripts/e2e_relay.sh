#!/usr/bin/env bash
# Relay e2e suite: run Playwright THROUGH a front proxy that uses the production relay rules
# (deploy/relay/jam.rules.caddy, byte-for-byte the file the public relay imports). Run it on the Mac test
# machine against a dev server on another host, like scripts/e2e.sh:
#   scripts/e2e_relay.sh <server-host-ip> [server-port] [relay-port] [playwright args...]
# Every change that touches the public site (API, auth, relay rules, the home page) must pass this suite.
#
# Chain: browser -> http://127.0.0.1:<relay-port> (Caddy, production rules) -> 127.0.0.1:<server-port>
# (tcp_forward.py) -> <server-host-ip>:<server-port> (the Jam dev server). The dev server should run with
# JAM_TEST_FAIL_TITLE=__e2e_fail__ (the retry test) and the fake Jamendo API (scripts/fake_jamendo.py).
set -uo pipefail
HOST="$1"; PORT="${2:-8765}"; RPORT="${3:-8780}"; shift; shift || true; shift || true
PW_ARGS=("$@"); [ ${#PW_ARGS[@]} -gt 0 ] || PW_ARGS=(tests/relay.spec.js)   # default: the relay spec only
cd "$(dirname "$0")/.."
ROOT="$PWD"
CADDY="${JAM_CADDY:-$(command -v caddy || echo /opt/homebrew/bin/caddy)}"
[ -x "$CADDY" ] || { echo "caddy not found (brew install caddy, or set JAM_CADDY)" >&2; exit 2; }
for p in $(lsof -t -iTCP:$PORT -sTCP:LISTEN 2>/dev/null) $(lsof -t -iTCP:$RPORT -sTCP:LISTEN 2>/dev/null); do
  ps -o command= -p "$p" | grep -qE "tcp_forward.py|caddy run" && kill "$p"
done
sleep 0.5
TMP=$(mktemp -d)
python3 scripts/tcp_forward.py "$PORT" "$HOST" "$PORT" &
FWD=$!
cat > "$TMP/Caddyfile" <<EOF
{
	admin off
	auto_https off
	storage file_system $TMP/data
}
http://127.0.0.1:$RPORT {
	import $ROOT/deploy/relay/jam.rules.caddy 127.0.0.1:$PORT
}
EOF
"$CADDY" run --config "$TMP/Caddyfile" --adapter caddyfile > "$TMP/caddy.log" 2>&1 &
CAD=$!
trap 'kill $FWD $CAD 2>/dev/null; rm -rf "$TMP"' EXIT
for i in $(seq 1 40); do curl -fsS -m 2 -o /dev/null "http://127.0.0.1:$RPORT/api/info" && break; sleep 0.3; done
EVID="${JAM_EVIDENCE:-../docs/evidence/e2e-relay}"   # relative to e2e/
{
  echo "# $(date -u +%FT%TZ) relay=$("$CADDY" version | cut -d' ' -f1) rules=$(shasum -a 256 deploy/relay/jam.rules.caddy | cut -c1-16)"
  # the relay itself, before any browser: no token -> 403 from the relay, the public POSTs pass
  for c in "DELETE /api/songs/abcdef1234" "PATCH /api/songs/abcdef1234" "POST /api/songs/abcdef1234/retry" "PUT /api/songs/abcdef1234" "GET /api/info"; do
    m=${c%% *}; u=${c#* }; printf "%s %s -> %s\n" "$m" "$u" "$(curl -s -o /dev/null -w '%{http_code}' -X "$m" "http://127.0.0.1:$RPORT$u")"
  done
} | tee "$TMP/probe.txt"
cd e2e
mkdir -p "$EVID"; cp "$TMP/probe.txt" "$EVID/relay-probe.txt"
JAM_RELAY=1 JAM_URL="http://127.0.0.1:$RPORT" JAM_EVIDENCE="$EVID" JAM_DEMO_DIR=../demo/source \
  npx playwright test "${PW_ARGS[@]}" 2>&1 | tee "$EVID/playwright.log"
rc=${PIPESTATUS[0]}
cp "$TMP/caddy.log" "$EVID/caddy.log" 2>/dev/null
exit "$rc"
