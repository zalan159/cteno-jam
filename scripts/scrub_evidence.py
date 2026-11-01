#!/usr/bin/env python3
"""Scrub machine-specific paths and LAN addresses from evidence files before they are committed.

    python scripts/scrub_evidence.py docs/evidence [extra-prefix ...]

Absolute work-dir prefixes become '<work>', home dirs '<home>', private IPv4 addresses
'<lan-ip>' (192.168.x.x). Text files only; binaries are left alone."""
import re
import sys
from pathlib import Path

root = Path(sys.argv[1])
extra = sys.argv[2:]
TEXT = {".log", ".json", ".jsonl", ".txt", ".md"}
rules = [(re.escape(p.rstrip("/")), "<work>") for p in extra]
rules += [
    (r"/Volumes/[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]*?/src", "<work>"),
    (r"/(?:home|Users)/[A-Za-z0-9_.-]+/CtenoDev/jam/src", "<work>"),
    (r"/(?:home|Users)/[A-Za-z0-9_.-]+", "<home>"),
    # home-LAN addresses only (10.x / 172.16-31 patterns also match package versions like 10.3.2.106,
    # and Docker's own bridge addresses say nothing about anyone's network)
    (r"(?<![\w.=-])192\.168\.\d{1,3}\.\d{1,3}\b", "<lan-ip>"),
    (r"/tmp/pytest-of-[A-Za-z0-9_.-]+", "/tmp/pytest"),
]
n = 0
for p in root.rglob("*"):
    if not p.is_file() or p.suffix not in TEXT:
        continue
    s = p.read_text(encoding="utf-8", errors="replace")
    t = s
    for a, b in rules:
        t = re.sub(a, b, t)
    if t != s:
        p.write_text(t, encoding="utf-8")
        n += 1
        print("scrubbed", p)
print(n, "files changed")
