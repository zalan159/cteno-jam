#!/usr/bin/env bash
# Deploy the static demo + a player-only sync server to a small Linux box behind Caddy.
#   JAM_DEPLOY_SSH="root@host" JAM_DEPLOY_DOMAIN=jam.example.com bash scripts/deploy_relay.sh
# Optional: JAM_DEPLOY_SSH_OPTS="-i ~/.ssh/key", JAM_DEPLOY_PORT (local sync port, default 8791).
#
# What it installs on the box (Ubuntu/Debian with Caddy already serving other sites):
#   /srv/jam/www        static player with the bundled CC0 demo songs (no uploads, no processing)
#   /opt/cteno-jam      python venv running `cteno-jam` with JAM_MODE=player (sync rooms only,
#                       no torch; ~40 MB RAM) as the systemd unit cteno-jam-sync
#   a Caddy site block for $JAM_DEPLOY_DOMAIN in /etc/caddy/sites/cteno-jam.caddy, imported
#   from /etc/caddy/Caddyfile (other sites are left untouched)
set -euo pipefail
cd "$(dirname "$0")/.."
SSH_T="${JAM_DEPLOY_SSH:?set JAM_DEPLOY_SSH=user@host}"; DOMAIN="${JAM_DEPLOY_DOMAIN:?set JAM_DEPLOY_DOMAIN}"
OPTS=(${JAM_DEPLOY_SSH_OPTS:-}); PORT="${JAM_DEPLOY_PORT:-8791}"
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT

python3 scripts/build_demo.py static "$TMP/www" --sync-url "wss://$DOMAIN"
mkdir -p "$TMP/pkg"; cp -R server/pyproject.toml server/README.md server/cteno_jam "$TMP/pkg/"
find "$TMP" -name __pycache__ -prune -exec rm -rf {} +
tar -C "$TMP" -czf "$TMP/jam.tgz" www pkg

scp "${OPTS[@]}" -q "$TMP/jam.tgz" "$SSH_T:/tmp/cteno-jam.tgz"
ssh "${OPTS[@]}" "$SSH_T" DOMAIN="$DOMAIN" PORT="$PORT" bash -s <<'REMOTE'
set -euo pipefail
command -v python3 >/dev/null
python3 -c 'import ensurepip' 2>/dev/null || { apt-get update -qq && apt-get install -y -qq python3-venv >/dev/null; }
id cteno-jam >/dev/null 2>&1 || useradd --system --home /opt/cteno-jam --shell /usr/sbin/nologin cteno-jam
mkdir -p /srv/jam /opt/cteno-jam
rm -rf /tmp/cteno-jam-new && mkdir /tmp/cteno-jam-new && tar -C /tmp/cteno-jam-new -xzf /tmp/cteno-jam.tgz
rm -rf /srv/jam/www.new && mv /tmp/cteno-jam-new/www /srv/jam/www.new
rm -rf /srv/jam/www.old; [ -d /srv/jam/www ] && mv /srv/jam/www /srv/jam/www.old; mv /srv/jam/www.new /srv/jam/www; rm -rf /srv/jam/www.old
rm -rf /opt/cteno-jam/pkg && mv /tmp/cteno-jam-new/pkg /opt/cteno-jam/pkg
[ -x /opt/cteno-jam/venv/bin/python ] || python3 -m venv /opt/cteno-jam/venv
/opt/cteno-jam/venv/bin/pip install -q --upgrade /opt/cteno-jam/pkg
mkdir -p /opt/cteno-jam/data && chown -R cteno-jam /opt/cteno-jam/data
cat > /etc/systemd/system/cteno-jam-sync.service <<EOF
[Unit]
Description=Cteno Jam sync rooms (player mode, no processing)
After=network.target
[Service]
User=cteno-jam
Environment=JAM_MODE=player JAM_HOST=127.0.0.1 JAM_PORT=$PORT JAM_DATA_DIR=/opt/cteno-jam/data JAM_SEED_DEMO=0 JAM_WEB_DIR=/srv/jam/www
ExecStart=/opt/cteno-jam/venv/bin/cteno-jam
Restart=always
MemoryMax=200M
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=/opt/cteno-jam/data
[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload; systemctl enable --now cteno-jam-sync >/dev/null 2>&1; systemctl restart cteno-jam-sync
mkdir -p /etc/caddy/sites
cat > /etc/caddy/sites/cteno-jam.caddy <<EOF
$DOMAIN {
	encode gzip
	handle /ws/* {
		reverse_proxy 127.0.0.1:$PORT
	}
	handle /api/info {
		reverse_proxy 127.0.0.1:$PORT
	}
	handle {
		root * /srv/jam/www
		header /demo/* Cache-Control "public, max-age=86400"
		file_server
	}
}
EOF
grep -q '^import sites/\*.caddy' /etc/caddy/Caddyfile || printf '\nimport sites/*.caddy\n' >> /etc/caddy/Caddyfile
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null 2>&1
systemctl reload caddy
sleep 2
curl -fsS "http://127.0.0.1:$PORT/api/info"; echo
systemctl --no-pager -l status cteno-jam-sync | head -5
rm -f /tmp/cteno-jam.tgz; rm -rf /tmp/cteno-jam-new
REMOTE
echo "deployed: https://$DOMAIN"
