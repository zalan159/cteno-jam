#!/usr/bin/env bash
# From the dev machine: ship the tree to both test machines, restart the dev server (with the fake Jamendo API,
# the bundled demo songs and the e2e failure marker), then run on the Mac
#   1. the phone suite     scripts/e2e.sh        (direct to the server; WebKit + Chromium at iPhone size, desktop)
#   2. the relay suite     scripts/e2e_relay.sh  (through a Caddy with the production relay rules)
#   scripts/e2e_all.sh [playwright args for the phone suite...]
# Both suites must pass for every change; changes to anything public (API, auth, relay rules, home page) are not
# done without the relay suite.
set -uo pipefail
cd "$(dirname "$0")/.."
# JAM_SERVER_HOST: ssh host running the dev server; JAM_SERVER_IP: its LAN address as seen from the Mac;
# JAM_MAC_HOST: ssh host of the Mac with Playwright and Caddy; JAM_*_ROOT: work dirs (default CtenoDev/jam).
SRV=${JAM_SERVER_HOST:?set JAM_SERVER_HOST}; SRV_IP=${JAM_SERVER_IP:?set JAM_SERVER_IP}; MAC=${JAM_MAC_HOST:?set JAM_MAC_HOST}
SRV_ROOT=${JAM_SERVER_ROOT:-CtenoDev/jam}; MAC_ROOT=${JAM_MAC_ROOT:-CtenoDev/jam}
PORT=${JAM_E2E_PORT:-8765}; FJ=${JAM_FAKE_JAMENDO_PORT:-8782}; RPORT=${JAM_RELAY_PORT:-8780}
JAM_SLAVE_ROOT="$SRV_ROOT" scripts/slave "$SRV" -- "D=\$HOME/$SRV_ROOT/data-e2e; mkdir -p \$D; rm -rf \$D/songs; \
  [ -f \$HOME/$SRV_ROOT/fake-jamendo.pid ] && kill \$(cat \$HOME/$SRV_ROOT/fake-jamendo.pid) 2>/dev/null; \
  (setsid nohup python3 scripts/fake_jamendo.py $FJ > \$D/fake-jamendo.log 2>&1 & echo \$! > \$HOME/$SRV_ROOT/fake-jamendo.pid); \
  JAM_SEED_DEMO=1 JAM_JAMENDO_CLIENT_ID=e2e JAM_JAMENDO_API_URL=http://127.0.0.1:$FJ/v3.0 JAM_TEST_FAIL_TITLE=__e2e_fail__ \
  JAM_MAX_DURATION_S=600 JAM_MAX_UPLOAD_MB=50 bash scripts/serve_slave.sh $PORT \$D >/dev/null 2>&1; echo server restarted"
T='T=$(command -v timeout || command -v gtimeout)'
JAM_SLAVE_ROOT="$MAC_ROOT" scripts/slave "$MAC" -- "$T; rm -rf docs/evidence/e2e docs/evidence/e2e-relay; \
  \$T 2400 bash scripts/e2e.sh $SRV_IP $PORT $* > /tmp/jam-e2e.log 2>&1; echo EXIT=\$? >> /tmp/jam-e2e.log; \
  \$T 1500 bash scripts/e2e_relay.sh $SRV_IP $PORT $RPORT > /tmp/jam-e2e-relay.log 2>&1; echo EXIT=\$? >> /tmp/jam-e2e-relay.log; \
  echo '== phone suite'; grep -E '✘|EXIT|passed|failed|skipped' /tmp/jam-e2e.log | cut -c1-300 | tail -12; \
  echo '== relay suite'; grep -E '✘|EXIT|passed|failed|skipped| -> ' /tmp/jam-e2e-relay.log | cut -c1-300 | tail -14; \
  grep -q 'EXIT=0' /tmp/jam-e2e.log && grep -q 'EXIT=0' /tmp/jam-e2e-relay.log"
