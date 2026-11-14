"""Run a command behind a private, throwaway local gateway.

    python -m canary.gemini.with_gateway --replay results/gemini/replay -- python -m canary.gemini.showcase --check ...
    python -m canary.gemini.with_gateway --record results/gemini/replay -- python -m canary.gemini.ladder ...

Starts `canary.gemini.gateway` on 127.0.0.1 (free port) with a fresh 0600 token in a temp dir, runs the
command with GEMINI_GATEWAY_URL / GEMINI_GATEWAY_TOKEN_FILE set (and GEMINI_API_KEY blanked, so the
command can only reach Gemini through the gateway), then stops the gateway. Replay needs no key at all.
Extra gateway flags go before `--` (e.g. --max-concurrency 16 --model-limit gemini-4-carbon=8).
"""
from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--" not in argv:
        print(__doc__, file=sys.stderr)
        return 2
    i = argv.index("--")
    gw_args, cmd = argv[:i], argv[i + 1:]
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--ledger", default=None, help="CANARY_GEMINI_LEDGER for the command (e.g. a temp file)")
    known, gw_rest = p.parse_known_args(gw_args)
    port = _free_port()
    with tempfile.TemporaryDirectory(prefix="canary-gw-") as td:
        tok = Path(td) / "token"
        gw = subprocess.Popen([sys.executable, "-m", "canary.gemini.gateway", "--host", "127.0.0.1",
                               "--port", str(port), "--token-file", str(tok), "--max-hours", "6",
                               "--stats-dir", str(Path(td) / "stats"), *gw_rest])
        url = f"http://127.0.0.1:{port}"
        try:
            for _ in range(100):
                if gw.poll() is not None:
                    print("with_gateway: gateway exited early", file=sys.stderr)
                    return 1
                try:
                    urllib.request.urlopen(url + "/healthz", timeout=1).read()
                    break
                except OSError:
                    time.sleep(0.1)
            env = dict(os.environ, GEMINI_GATEWAY_URL=url, GEMINI_GATEWAY_TOKEN_FILE=str(tok), GEMINI_API_KEY="")
            env.pop("GEMINI_GATEWAY_TOKEN", None)
            env.pop("GEMINI_GATEWAY_CLIENT", None)
            if known.ledger:
                env["CANARY_GEMINI_LEDGER"] = known.ledger
            return subprocess.call(cmd, env=env)
        finally:
            gw.terminate()
            try:
                gw.wait(10)
            except subprocess.TimeoutExpired:
                gw.kill()


if __name__ == "__main__":
    sys.exit(main())
