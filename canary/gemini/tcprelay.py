"""Byte-level TCP relay (stdlib asyncio), used by the ssh -R fallback (fr8/gemini/tunnel_up.sh).

    python -m canary.gemini.tcprelay --listen 10.0.0.5:8787 --to 127.0.0.1:18787 [--max-hours 8]

sshd binds reverse forwards to loopback by default, so compute nodes cannot reach them; this relays the
cluster-internal address to that loopback port. It holds no key and does no auth itself (the gateway on the
other end of the tunnel checks the token on every request).
"""
from __future__ import annotations

import argparse
import asyncio
import sys


async def _pipe(r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
    try:
        while data := await r.read(65536):
            w.write(data)
            await w.drain()
    except (ConnectionError, asyncio.CancelledError):
        pass
    finally:
        try:
            w.close()
        except Exception:  # noqa: BLE001
            pass


async def serve(listen: tuple[str, int], to: tuple[str, int], max_hours: float) -> None:
    async def handle(cr, cw):
        try:
            ur, uw = await asyncio.open_connection(*to)
        except OSError:
            cw.close()
            return
        await asyncio.gather(_pipe(cr, uw), _pipe(ur, cw))

    srv = await asyncio.start_server(handle, *listen)
    print(f"tcprelay: {listen[0]}:{listen[1]} -> {to[0]}:{to[1]} (max_hours={max_hours})", flush=True)
    async with srv:
        if max_hours > 0:
            await asyncio.sleep(max_hours * 3600)  # hard stop; the server task ends with the context
        else:
            await srv.serve_forever()


def _hp(s: str) -> tuple[str, int]:
    h, _, p = s.rpartition(":")
    return h, int(p)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m canary.gemini.tcprelay")
    p.add_argument("--listen", required=True)
    p.add_argument("--to", required=True)
    p.add_argument("--max-hours", type=float, default=8.0)
    a = p.parse_args(argv)
    try:
        asyncio.run(serve(_hp(a.listen), _hp(a.to), a.max_hours))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
