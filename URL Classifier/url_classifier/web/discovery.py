"""UDP discovery so CleanNet on the same LAN finds the classifier API without a fixed IP."""

from __future__ import annotations

import socket
import threading

DISCOVERY_PORT = 45322
_REQUEST = b"CLEANNET_DISCOVER_V1\n"


def _lan_ipv4() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def start_discovery_responder(http_port: int) -> None:
    """
    Listen on UDP ``DISCOVERY_PORT``; reply to discovery probes with the HTTP classify URL.

    Phones broadcast ``CLEANNET_DISCOVER_V1`` and receive ``CLEANNET_API|http://<lan-ip>:<port>/v1/classify``.
    """

    def run() -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("0.0.0.0", DISCOVERY_PORT))
        except OSError as e:
            print(f"  Discovery UDP: bind failed ({e}). Allow UDP {DISCOVERY_PORT} or set CLEANNET_DISCOVERY=0.\n", flush=True)
            return
        print(f"  Discovery: UDP {DISCOVERY_PORT} — app finds this PC automatically on Wi‑Fi\n", flush=True)
        while True:
            try:
                data, addr = sock.recvfrom(512)
            except OSError:
                break
            req = data.strip()
            if req != _REQUEST.strip():
                continue
            ip = _lan_ipv4()
            url = f"http://{ip}:{http_port}/v1/classify"
            resp = f"CLEANNET_API|{url}\n".encode("utf-8")
            try:
                sock.sendto(resp, addr)
            except OSError:
                pass

    t = threading.Thread(target=run, daemon=True, name="cleannet-discovery-udp")
    t.start()
