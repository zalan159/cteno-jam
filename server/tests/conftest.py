import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import os

# Most API tests upload stand-in bytes ("ID3fake") that ffprobe would refuse; the upload-time probe
# (JAM_CHECK_UPLOADS) is switched on explicitly by the tests that check it (test_owner.py, test_upload_checks.py).
os.environ.setdefault("JAM_CHECK_UPLOADS", "0")


def owner(resp):
    """X-Jam-Owner header for the song created by an upload/import response."""
    return {"X-Jam-Owner": resp.json()["owner_token"]}
