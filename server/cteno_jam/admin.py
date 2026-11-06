"""Server-side song administration (for whoever runs the server; no HTTP, no token needed).

    python -m cteno_jam.admin list [--failed] [--no-owner]   id, status, owner token yes/no, created, title
    python -m cteno_jam.admin show <id>                      the song's metadata (never the token hash)
    python -m cteno_jam.admin delete <id> [<id> ...] [--yes] delete songs (demo songs too, with --force-demo)

Reads JAM_DATA_DIR like the server. In the docker deployment run it inside the container, e.g.
    docker compose exec jam python -m cteno_jam.admin list --failed
    docker compose exec jam python -m cteno_jam.admin delete 36c43941e5 --yes

A song that is being processed right now is deleted on disk; its worker then stops on its own
(the queue skips songs whose directory is gone).
"""
from __future__ import annotations

import argparse
import json
import sys
import time

from . import config, store


def _row(m) -> str:
    owner = "token" if m.get("owner_hash") else "-"
    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(m.get("created") or 0))
    demo = " demo" if m.get("demo") else ""
    return "%-14s %-10s %-5s %s%s  %s" % (m["id"], m.get("status"), owner, when, demo, m.get("title") or "")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m cteno_jam.admin", description="Cteno Jam song administration")
    sub = ap.add_subparsers(dest="cmd", required=True)
    ls = sub.add_parser("list", help="list songs")
    ls.add_argument("--failed", action="store_true", help="only failed songs")
    ls.add_argument("--no-owner", action="store_true", help="only songs without a management token (uploaded before tokens existed)")
    sh = sub.add_parser("show", help="print one song's metadata")
    sh.add_argument("id")
    rm = sub.add_parser("delete", help="delete songs")
    rm.add_argument("ids", nargs="+")
    rm.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    rm.add_argument("--force-demo", action="store_true", help="also delete bundled demo songs")
    a = ap.parse_args(argv)

    st = store.Store(config.get().songs_dir)
    if a.cmd == "list":
        for m in st.list():
            if a.failed and m.get("status") != "failed":
                continue
            if a.no_owner and m.get("owner_hash"):
                continue
            print(_row(m))
        return 0
    if a.cmd == "show":
        try:
            m = st.meta(a.id)
        except store.NotFound:
            print("no such song: %s" % a.id, file=sys.stderr)
            return 1
        m = {k: v for k, v in m.items() if k != "owner_hash"}
        m["has_owner_token"] = bool(st.meta(a.id).get("owner_hash"))
        print(json.dumps(m, ensure_ascii=False, indent=1))
        return 0
    # delete
    rc = 0
    for sid in a.ids:
        try:
            m = st.meta(sid)
        except store.NotFound:
            print("no such song: %s" % sid, file=sys.stderr)
            rc = 1
            continue
        if m.get("demo") and not a.force_demo:
            print("skip %s: demo song (add --force-demo)" % sid, file=sys.stderr)
            rc = 1
            continue
        if not a.yes:
            ans = input("delete %s? [y/N] " % _row(m)).strip().lower()
            if ans not in ("y", "yes"):
                print("kept %s" % sid)
                continue
        st.delete(sid)
        print("deleted %s  %s" % (sid, m.get("title") or ""))
    return rc


if __name__ == "__main__":
    sys.exit(main())
