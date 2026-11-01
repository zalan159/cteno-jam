#!/usr/bin/env bash
# Smoke-test a built image: start it, check the API and the seeded demo, upload a demo song,
# wait until processing is done and print the result. Removes the container afterwards.
#   bash scripts/docker_smoke.sh <image> [extra docker run args...]
#   e.g. bash scripts/docker_smoke.sh cteno-jam:gpu --gpus all
set -uo pipefail
IMG="$1"; shift
cd "$(dirname "$0")/.."
NAME=jam-smoke-$$; PORT=${SMOKE_PORT:-8766}
trap 'docker rm -f $NAME >/dev/null 2>&1' EXIT
echo "image: $(docker images "$IMG" --format '{{.Repository}}:{{.Tag}} {{.Size}}')"
docker run -d --name $NAME -p $PORT:8765 -e JAM_SEED_DEMO=1 "$@" "$IMG" >/dev/null
for i in $(seq 90); do curl -fs "http://127.0.0.1:$PORT/api/info" >/dev/null && break; sleep 1; done
echo "info: $(curl -s "http://127.0.0.1:$PORT/api/info")"
curl -s "http://127.0.0.1:$PORT/api/songs" | python3 -c 'import json,sys; print("seeded:", [(s["id"], s["status"]) for s in json.load(sys.stdin)["songs"]])'
docker exec $NAME python -c 'import torch; print("torch", torch.__version__, "cuda available:", torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else "")'
T0=$(date +%s)
# the demo LRC is passed as user lyrics (the synthetic voice is not transcribable)
ID=$(curl -s -F file=@demo/source/twinkle.mp3 -F "lyrics=<demo/source/twinkle.lrc" -F "title=Twinkle (smoke)" "http://127.0.0.1:$PORT/api/songs" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
echo "uploaded id=$ID"
LAST=""
for i in $(seq 600); do
  S=$(curl -s "http://127.0.0.1:$PORT/api/songs/$ID" | python3 -c 'import json,sys; d=json.load(sys.stdin); d=d.get("song", d); print(d["status"], d.get("stage"), d.get("error") or "")')
  [ "$S" != "$LAST" ] && echo "$(( $(date +%s) - T0 ))s $S" && LAST="$S"
  case "$S" in ready*|failed*) break ;; esac
  sleep 2
done
curl -s "http://127.0.0.1:$PORT/api/songs/$ID" | python3 -c 'import json,sys; d=json.load(sys.stdin); d=d.get("song", d); print("device:", d.get("device"), "timings:", d.get("timings"))'
curl -s "http://127.0.0.1:$PORT/api/songs/$ID/song.json" | python3 -c '
import json,sys; d=json.load(sys.stdin); a=d.get("analysis", d)
print("top-level keys:", sorted(d)[:12])
print("key:", a.get("key"), "tempo:", a.get("tempo"), "chords:", len(a.get("chords") or []), "lyric lines:", len((a.get("lyrics") or {}).get("lines") or []))'
echo "--- container log (tail)"; docker logs $NAME 2>&1 | grep -v '"GET /api/songs/' | tail -15
