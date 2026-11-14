"""Cut a committed showcase store out of a big ladder recording (keyless, no network).

    python -m canary.gemini.ladder_subset --store data/gemini/replay-ladder-full --name ladder-showcase -- \
        python -m canary.gemini.ladder --run-name ladder-v14 --models ... --levels high --tiers medium --seeds 0 \
        --out {out}

The full store (a gateway --record dir from `with_gateway --record ... -- python -m canary.gemini.ladder ...`) is
too big to commit. This replays the given ladder command against it behind a pass-through proxy that computes each
request's replay key exactly as canary.gemini.gateway does (request_key over tag + method + path + query without
the key + canonical body) and copies the matching stored responses (<h>.json.gz and its repeats) into
results/gemini/replay-<name>/. It then writes a canary.gemini.lab_replay manifest, so `make lab-replay` replays the
subset keyless and checks every episode step for step. The command must pass the same --run-name as the recording
(the replay tag is derived from the ladder's ledger meta, which includes it).
"""
from __future__ import annotations

import argparse
import http.server
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

ROOT = Path(__file__).resolve().parents[2]


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def make_proxy(upstream: str, full: Path, sub: Path, copied: set):
    from canary.gemini.gateway import REPLAY_TAG, request_key, strip_key

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):  # quiet
            pass

        def _relay(self):
            n = int(self.headers.get("content-length") or 0)
            body = self.rfile.read(n) if n else b""
            u = urlsplit(self.path)
            key = request_key(self.command, u.path, strip_key(u.query), body, self.headers.get(REPLAY_TAG, ""))
            for f in sorted((full / key[:2]).glob(f"{key}*.json.gz")):
                dst = sub / key[:2] / f.name
                if not dst.exists():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(f, dst)
                copied.add(f.name)
            hdrs = {k: v for k, v in self.headers.items() if k.lower() not in ("host", "content-length", "connection")}
            req = urllib.request.Request(upstream + self.path, data=body if body else None, headers=hdrs,
                                         method=self.command)
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    status, rh, data = r.status, r.headers, r.read()
            except urllib.error.HTTPError as e:
                status, rh, data = e.code, e.headers, e.read()
            self.send_response(status)
            for k, v in rh.items():
                if k.lower() not in ("content-length", "transfer-encoding", "connection", "content-encoding"):
                    self.send_header(k, v)
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        do_POST = do_GET = _relay

    return H


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd: list[str] = []
    if "--" in argv:
        i = argv.index("--")
        argv, cmd = argv[:i], argv[i + 1:]
    ap = argparse.ArgumentParser(prog="python -m canary.gemini.ladder_subset", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--store", required=True, help="full gateway --record dir")
    ap.add_argument("--name", required=True, help="writes results/gemini/replay-<name>/")
    ap.add_argument("--dest", default=None, help="parent dir for replay-<name>/ (default results/gemini)")
    ap.add_argument("--work", default=None, help="episode output dir (default data/gemini/replay-record/<name>)")
    a = ap.parse_args(argv)
    if not cmd:
        ap.error("needs the ladder command after --, with {out} as its output dir")
    from canary.gemini import lab_replay
    full = Path(a.store).expanduser().resolve()
    sub = Path(a.dest or lab_replay.RESULTS) / f"replay-{a.name}"
    if sub.exists():
        print(f"ladder_subset: {sub} exists; remove it first", file=sys.stderr)
        return 1
    sub.mkdir(parents=True)
    out = Path(a.work) if a.work else ROOT / "data" / "gemini" / "replay-record" / a.name
    shutil.rmtree(out, ignore_errors=True)
    tmp = Path(tempfile.mkdtemp(prefix="ladder-subset-"))
    tok = secrets.token_hex(16)
    (tmp / "token").write_text(tok + "\n")
    os.chmod(tmp / "token", 0o600)
    gport, pport = _free_port(), _free_port()
    env = {k: v for k, v in os.environ.items() if k not in ("GEMINI_API_KEY", "GOOGLE_API_KEY")}
    gw = subprocess.Popen([sys.executable, "-m", "canary.gemini.gateway", "--port", str(gport), "--replay", str(full),
                           "--token-file", str(tmp / "token"), "--key-file", "/dev/null", "--stats-dir",
                           str(tmp / "stats"), "--max-hours", "2"], cwd=ROOT, env=env,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    copied: set = set()
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", pport), make_proxy(f"http://127.0.0.1:{gport}", full, sub,
                                                                           copied))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{gport}/healthz", timeout=1)
                break
            except Exception:  # noqa: BLE001
                time.sleep(0.1)
        run = [c.replace("{out}", str(out)) for c in cmd]
        if run and run[0] in ("python", "python3"):
            run = [sys.executable, *run[1:]]
        env.update(GEMINI_GATEWAY_URL=f"http://127.0.0.1:{pport}", GEMINI_GATEWAY_TOKEN_FILE=str(tmp / "token"),
                   GEMINI_API_KEY="", CANARY_LLM_MAX_RETRIES="0",
                   CANARY_GEMINI_LEDGER=str(out.parent / f"{a.name}-ledger.jsonl"))
        rc = subprocess.call(run, cwd=ROOT, env=env)
    finally:
        srv.shutdown()
        gw.terminate()
        gw.wait(timeout=10)
        shutil.rmtree(tmp, ignore_errors=True)
    if rc != 0:
        return rc
    eps = lab_replay.summarize(out)
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
    man = {"name": a.name, "cmd": cmd, "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "git_sha": sha,
           "episodes": eps, "cut_from": str(Path(a.store)), "responses": len(copied)}
    (sub / "manifest.json").write_text(json.dumps(man, indent=1, sort_keys=True) + "\n")
    size = sum(f.stat().st_size for f in sub.rglob("*.json.gz"))
    print(f"ladder_subset: {sum(len(v) for v in eps.values())} episodes, {len(copied)} responses, "
          f"{size / 1e6:.1f} MB -> {sub}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
