#!/usr/bin/env python3
"""Fake model for offline tests: an OpenAI Responses-API endpoint with a scripted agent.

It behaves like a tiny deterministic "reviewer": on the first request it calls get_overview,
then get_chords, then check_patches, then final_result with patches computed from what the
tools returned (respell out-of-key enharmonics, merge 1-beat blips) PLUS deliberately invalid
patches, so tests can prove the server rejects them.

    MOCK_PORT=18997 python fake_model.py
"""
import json
import os
import re
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from cteno_jam import theory  # noqa: E402

LOG = os.environ.get("MOCK_LOG", "")


def outputs(req):
    """Tool results so far, in order: [(name, parsed)]."""
    names = {}
    out = []
    for item in req.get("input") or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "function_call":
            names[item.get("call_id")] = item.get("name")
        elif item.get("type") == "function_call_output":
            raw = item.get("output")
            if isinstance(raw, list):
                raw = "".join(x.get("text", "") for x in raw if isinstance(x, dict))
            try:
                val = json.loads(raw)
            except (TypeError, ValueError):
                m = re.search(r"\{.*\}", str(raw), re.S)
                val = json.loads(m.group(0)) if m else raw
            out.append((names.get(item.get("call_id")), val))
    return out


def plan(req):
    done = outputs(req)
    have = [n for n, _ in done]
    tools = [t.get("name") for t in req.get("tools") or []]
    if "get_overview" not in have:
        return "get_overview", {}
    if "get_chords" not in have:
        return "get_chords", {"offset": 0, "limit": 120}
    ov = next(v for n, v in done if n == "get_overview")
    ch = next(v for n, v in done if n == "get_chords")
    key = theory.parse_key(ov.get("key") or "")
    patches = []
    chords = ch.get("chords", [])
    for c in chords:
        if c["chord"] != "N" and key:
            sp = theory.spell(c["chord"], key)
            if sp != c["chord"]:
                patches.append({"op": "respell_chord", "id": c["id"], "chord": sp,
                                "reason": "In %s this chord is spelled %s." % (key.name, sp)})
    for i, c in enumerate(chords):
        if c.get("beats") == 1 and 0 < i < len(chords) - 1:
            patches.append({"op": "merge_chord", "id": c["id"], "into": "prev",
                            "reason": "Lasts one beat between longer chords: likely a misdetection."})
    if chords:
        patches.append({"op": "add_section", "start": chords[0]["start"], "end": chords[-1]["end"], "label": "verse",
                        "reason": "Single repeated progression; one verse section."})
    patches.append({"op": "set_rhythm", "kind": "strum", "pattern": "D-DU-UDU", "reason": "Steady 4/4 pop strum."})
    # invalid on purpose:
    patches.append({"op": "rewrite_song", "reason": "should be rejected: unknown op"})
    patches.append({"op": "respell_chord", "id": chords[0]["id"] if chords else "c001", "chord": "Bbm7",
                    "reason": "should be rejected: not enharmonic"})
    patches.append({"op": "merge_chord", "id": "c999", "into": "prev", "reason": "should be rejected: no such id"})
    if "check_patches" not in have:
        return "check_patches", {"patches": patches}
    if "final_result" in tools:
        return "final_result", {"summary": "Fake review: respelled chords for the key, merged blips, added a verse.",
                                "patches": patches}
    return None, None


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._send({"object": "list", "data": [{"id": "fake-reviewer", "object": "model"}]})

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers.get("content-length", 0))) or b"{}")
        if os.environ.get("MOCK_DUMP"):
            with open(os.environ["MOCK_DUMP"], "a") as f:
                f.write(json.dumps(req) + "\n")
        name, args = plan(req)
        if LOG:
            with open(LOG, "a") as f:
                f.write(json.dumps({"path": self.path, "tools": [t.get("name") for t in req.get("tools") or []],
                                    "call": name}) + "\n")
        rid = "resp_%d" % int(time.time() * 1000)
        if name:
            item = {"type": "function_call", "id": "fc_%s" % rid, "call_id": "call_%s" % rid, "name": name,
                    "arguments": json.dumps(args), "status": "completed"}
        else:
            item = {"type": "message", "id": "msg_1", "role": "assistant", "status": "completed",
                    "content": [{"type": "output_text", "text": "done", "annotations": []}]}
        done = {"id": rid, "object": "response", "status": "completed", "model": "fake-reviewer", "output": [item],
                "usage": {"input_tokens": 10, "output_tokens": 3, "total_tokens": 13}}
        if not req.get("stream"):
            return self._send(done)
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.end_headers()
        ev = [("response.created", {"type": "response.created", "response": dict(done, status="in_progress", output=[])}),
              ("response.output_item.added", {"type": "response.output_item.added", "output_index": 0,
                                              "item": dict(item, **({"arguments": ""} if name else {"content": []}))})]
        if name:
            ev.append(("response.function_call_arguments.delta", {"type": "response.function_call_arguments.delta",
                       "output_index": 0, "item_id": item["id"], "delta": item["arguments"]}))
            ev.append(("response.function_call_arguments.done", {"type": "response.function_call_arguments.done",
                       "output_index": 0, "item_id": item["id"], "arguments": item["arguments"]}))
        else:
            ev.append(("response.output_text.delta", {"type": "response.output_text.delta", "output_index": 0,
                       "content_index": 0, "item_id": "msg_1", "delta": "done"}))
        ev.append(("response.output_item.done", {"type": "response.output_item.done", "output_index": 0, "item": item}))
        ev.append(("response.completed", {"type": "response.completed", "response": done}))
        for n, obj in ev:
            self.wfile.write(("event: %s\ndata: %s\n\n" % (n, json.dumps(obj))).encode())
            self.wfile.flush()


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(os.environ.get("MOCK_PORT", "18997"))), H).serve_forever()
