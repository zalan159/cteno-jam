#!/usr/bin/env bash
# Unit tests (server pytest + web node:test), logs to docs/evidence/unit/. Run on a test machine:
#   scripts/slave <host> --pull docs/evidence/unit -- bash scripts/unit.sh
set -uo pipefail
cd "$(dirname "$0")/.."
# ffmpeg/ffprobe: a static build in ~/CtenoDev/jam/tools on the test machine, else the system one
export PATH="$HOME/CtenoDev/jam/tools:$HOME/.local/node/bin:$PATH"
OUT=docs/evidence/unit; mkdir -p "$OUT"
PY=${PYTHON:-venv/bin/python}
{
  echo "# $(date -u +%FT%TZ) $(uname -sr) $($PY -V) ffprobe=$(command -v ffprobe >/dev/null && echo yes || echo no)"
  (cd server && "../$PY" -m pytest -q -p no:cacheprovider -W ignore::DeprecationWarning 2>&1)
} > "$OUT/pytest.log"
P=$(tail -1 "$OUT/pytest.log" | grep -qE "failed|error" && echo 1 || echo 0)
{
  echo "# $(date -u +%FT%TZ) node $(node -v)"
  node --test web/test/*.test.mjs 2>&1
} > "$OUT/node-test.log"
N=$?
tail -1 "$OUT/pytest.log"; grep -E "^# (pass|fail)" "$OUT/node-test.log"
echo "pytest=$P node=$N"
[ "$P" = 0 ] && [ "$N" = 0 ]
