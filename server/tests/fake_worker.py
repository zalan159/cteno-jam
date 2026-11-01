"""Stand-in for `python -m cteno_jam.worker` in API tests: writes a fixed analysis."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from cteno_jam import store  # noqa: E402
from test_patches import song  # noqa: E402

root, sid = Path(sys.argv[1]), sys.argv[2]
st = store.Store(root)
m = st.meta(sid)
st.update(sid, status="processing", attempts=int(m.get("attempts", 0)) + 1, stage="separate", progress=0.3)
src = st.original(sid)
if src.read_bytes().startswith(b"FAIL"):
    st.update(sid, status="failed", error="not a readable audio file (fake)")
    sys.exit(2)
time.sleep(0.2)
(st.dir(sid) / "stems").mkdir(exist_ok=True)
for k in ("vocals", "guitar", "piano", "bass", "drums", "other", "mix"):
    (st.dir(sid) / "stems" / (k + ".mp3")).write_bytes(b"ID3")
st.set_base(sid, song())
st.update(sid, status="ready", stage="done", progress=1.0, ai={"status": "not_configured"})
