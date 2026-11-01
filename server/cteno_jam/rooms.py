"""Sync rooms: one device plays (the host), others follow (viewers) or steer (remotes).

Protocol (JSON over one WebSocket per device, /ws/room/<code>):
  client -> server
    {"t":"hello","role":"host|viewer|remote","name":"..."}
    {"t":"ping","c":<client ms>}                         -> {"t":"pong","c":..,"s":<server ms>}
    {"t":"state", ...state}            (host only)       -> broadcast {"t":"state", ...}
    {"t":"cmd","cmd":"play|pause|seek|rate|transpose|mute|loop|song|next|prev","arg":...} (remote)
                                                          -> forwarded to the host(s)
  server -> client
    {"t":"welcome","room":code,"state":<last state or null>,"peers":n,"s":<server ms>}
    {"t":"peers","n":..,"hosts":..,"remotes":..}

State is {"song":id,"playing":bool,"pos":seconds at "at","at":server ms,"rate":r,"tr":semitones,
"capo":fret,"loop":[a,b]|null,"muted":[stems],"view":"sheet|stage"}. Followers compute the live
position as pos + (now_server - at)/1000 * rate, so they stay in step without streaming time.
"""
from __future__ import annotations

import asyncio
import json
import secrets
import time
from typing import Dict, Optional, Set

ALPH = "23456789abcdefghjkmnpqrstuvwxyz"  # no 0/1/i/l/o


def now_ms() -> int:
    return int(time.time() * 1000)


def new_code(n: int = 6) -> str:
    return "".join(secrets.choice(ALPH) for _ in range(n))


class Peer:
    def __init__(self, ws, role: str, name: str):
        self.ws, self.role, self.name = ws, role, name[:40]


class Room:
    def __init__(self, code: str):
        self.code = code
        self.peers: Set[Peer] = set()
        self.state: Optional[Dict] = None
        self.touched = time.time()

    def counts(self):
        r = {"t": "peers", "n": len(self.peers)}
        for role in ("host", "viewer", "remote"):
            r[role + "s"] = sum(1 for p in self.peers if p.role == role)
        return r


class Rooms:
    MAX_ROOMS = 500
    MAX_PEERS = 40

    def __init__(self):
        self.rooms: Dict[str, Room] = {}

    def get(self, code: str) -> Room:
        r = self.rooms.get(code)
        if r is None:
            self._gc()
            if len(self.rooms) >= self.MAX_ROOMS:
                raise OverflowError("too many rooms")
            r = self.rooms[code] = Room(code)
        r.touched = time.time()
        return r

    def _gc(self):
        cutoff = time.time() - 6 * 3600
        for c in [c for c, r in self.rooms.items() if not r.peers and r.touched < cutoff]:
            del self.rooms[c]

    async def send(self, peer: Peer, msg: Dict):
        try:
            await peer.ws.send_text(json.dumps(msg, ensure_ascii=False))
        except Exception:  # noqa: BLE001 — closed socket; removed by its own loop
            pass

    async def broadcast(self, room: Room, msg: Dict, roles=None, exclude: Optional[Peer] = None):
        await asyncio.gather(*[self.send(p, msg) for p in list(room.peers)
                               if p is not exclude and (roles is None or p.role in roles)])

    async def handle(self, ws, code: str):
        """Serve one WebSocket until it closes. `ws` is a Starlette WebSocket (already accepted)."""
        room = self.get(code)
        peer: Optional[Peer] = None
        try:
            while True:
                raw = await ws.receive_text()
                if len(raw) > 16_000:
                    continue
                try:
                    msg = json.loads(raw)
                except ValueError:
                    continue
                t = msg.get("t")
                if t == "ping":
                    await ws.send_text(json.dumps({"t": "pong", "c": msg.get("c"), "s": now_ms()}))
                elif t == "hello":
                    if len(room.peers) >= self.MAX_PEERS:
                        await ws.send_text(json.dumps({"t": "error", "error": "room full"}))
                        break
                    role = msg.get("role") if msg.get("role") in ("host", "viewer", "remote") else "viewer"
                    if peer:
                        room.peers.discard(peer)
                    peer = Peer(ws, role, str(msg.get("name") or ""))
                    room.peers.add(peer)
                    await self.send(peer, {**room.counts(), "t": "welcome", "room": code, "state": room.state, "s": now_ms()})
                    await self.broadcast(room, room.counts())
                elif t == "state" and peer and peer.role == "host":
                    st = {k: msg.get(k) for k in ("song", "playing", "pos", "rate", "tr", "capo", "loop", "muted", "view", "simple", "title")}
                    st["at"] = now_ms()
                    room.state = st
                    await self.broadcast(room, {"t": "state", **st}, exclude=peer)
                elif t == "cmd" and peer:
                    fwd = {"t": "cmd", "cmd": str(msg.get("cmd"))[:20], "arg": msg.get("arg"), "from": peer.name}
                    await self.broadcast(room, fwd, roles=("host",), exclude=peer)
        except Exception:  # noqa: BLE001 — disconnect
            pass
        finally:
            if peer:
                room.peers.discard(peer)
                await self.broadcast(room, room.counts())
