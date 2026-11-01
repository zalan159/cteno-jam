#!/usr/bin/env python3
"""Tiny TCP forwarder (test helper): expose a remote dev server as http://127.0.0.1:<port>.
Browsers treat localhost as a secure context, which AudioWorklet (pitch/tempo engine) needs.
    python3 scripts/tcp_forward.py 8765 <server-lan-ip> 8765
"""
import socket
import sys
import threading

lport, rhost, rport = int(sys.argv[1]), sys.argv[2], int(sys.argv[3])


def pipe(a, b):
    try:
        while True:
            d = a.recv(65536)
            if not d:
                break
            b.sendall(d)
    except OSError:
        pass
    finally:
        for s in (a, b):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


srv = socket.socket()
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("127.0.0.1", lport))
srv.listen(64)
while True:
    c, _ = srv.accept()
    try:
        r = socket.create_connection((rhost, rport), 5)
    except OSError:
        c.close()
        continue
    threading.Thread(target=pipe, args=(c, r), daemon=True).start()
    threading.Thread(target=pipe, args=(r, c), daemon=True).start()
