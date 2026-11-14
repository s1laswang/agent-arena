"""Choose the port for `make mcp`.

Default is 8765. If 8765 is busy and neither MCP_PORT nor CANARY_PORT is set,
use the next free port in 8766–8795 and say so on stderr.
A port set in the environment is pinned: if it is busy, exit 3.
"""
from __future__ import annotations

import os
import socket
import sys

DEFAULT = 8765
FALLBACK_END = 8795


class PortBusy(Exception):
    """The requested port cannot be bound, and this call must not pick another."""


def _can_bind(port: int) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", port))
    except OSError:
        return False
    else:
        return True
    finally:
        sock.close()


def choose_port(env: dict[str, str] | None = None, can_bind=None) -> int:
    env = os.environ if env is None else env
    can_bind = _can_bind if can_bind is None else can_bind
    pinned = env.get("MCP_PORT") or env.get("CANARY_PORT")
    if pinned:
        port = int(pinned)
        if not can_bind(port):
            raise PortBusy(f"make mcp: port {port} is busy (MCP_PORT/CANARY_PORT is set); not falling back")
        return port
    if can_bind(DEFAULT):
        return DEFAULT
    for port in range(DEFAULT + 1, FALLBACK_END + 1):
        if can_bind(port):
            print(f"make mcp: 8765 is busy, using {port}", file=sys.stderr)
            return port
    raise PortBusy(f"make mcp: no free port in {DEFAULT}–{FALLBACK_END}")


def main(argv: list[str] | None = None) -> int:
    del argv
    try:
        port = choose_port()
    except PortBusy as exc:
        print(exc, file=sys.stderr)
        return 3
    print(port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
