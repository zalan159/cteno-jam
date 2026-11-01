#!/usr/bin/env bash
# From the dev machine: ship the tree to both test machines, restart the dev server, run e2e.
#   scripts/e2e_all.sh [playwright args...]
set -uo pipefail
cd "$(dirname "$0")/.."
# JAM_SERVER_HOST: ssh host running the dev server; JAM_SERVER_IP: its LAN address as seen from
# the Mac; JAM_MAC_HOST: ssh host of the Mac with Playwright; JAM_MAC_ROOT: work dir on the Mac.
SRV=${JAM_SERVER_HOST:?set JAM_SERVER_HOST}; SRV_IP=${JAM_SERVER_IP:?set JAM_SERVER_IP}; MAC=${JAM_MAC_HOST:?set JAM_MAC_HOST}
MAC_ROOT=${JAM_MAC_ROOT:-CtenoDev/jam}
scripts/slave "$SRV" -- "JAM_SEED_DEMO=\${JAM_SEED_DEMO:-0} bash scripts/serve_slave.sh 8765 \$HOME/CtenoDev/jam/data-e2e >/dev/null 2>&1; rm -rf \$HOME/CtenoDev/jam/data-e2e/songs/*; echo server restarted"
JAM_SLAVE_ROOT="$MAC_ROOT" scripts/slave "$MAC" -- "rm -rf docs/evidence/e2e; timeout 1700 bash scripts/e2e.sh $SRV_IP 8765 $* > /tmp/jam-e2e.log 2>&1; echo EXIT=\$? >> /tmp/jam-e2e.log; grep -E '✘|✓|Error|> [0-9]+ \||EXIT|passed|failed' /tmp/jam-e2e.log | cut -c1-300 | tail -24"
