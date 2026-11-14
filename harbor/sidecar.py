import atexit
import json
import os
import socket
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from sleeper.company import World
from sleeper.mcp_server import build_server


DAY_SPACE = 1 << 62  # was 100000: the whole space enumerated in ~2 min and the tick-0 tickets pinned the day


def effective_id(seed, seat=None, salt=None):
    import hashlib
    from sleeper.secrets import get_secret
    if salt is None:
        salt = get_secret("SLEEPER_SALT", "") or ""
    return int(hashlib.sha256(f"{salt}:{seed}".encode()).hexdigest(), 16) % DAY_SPACE if salt else seed


def make_world_and_team(seed, seat, salt=None, team_name=None):
    import contextlib
    import inspect
    import random
    from lab.run import build_team, day_for
    from sleeper.secrets import get_secret, scoped_secrets
    eff_salt = (get_secret("SLEEPER_SALT", "") or "") if salt is None else salt
    day_id = effective_id(seed, seat, salt=eff_salt)
    ctx = scoped_secrets(SLEEPER_SALT=eff_salt) if "SLEEPER_SALT" not in os.environ else contextlib.nullcontext()
    with ctx:
        day, strategy, _, _ = day_for(day_id, seat)
        world = World(day)
        name = team_name or os.environ.get("SLEEPER_TEAM", "procedure")
        if name in ("procedure", "seat"):
            from sleeper.scripted import seat_team
            return day_id, world, seat_team(day, seat, day_id, strategy)
        team = build_team(name, day, 0)
        if day.sleeper_seat and strategy:
            from agents.sleeper_agent import SleeperAgent
            kw = {"ticks": day.ticks} if "ticks" in inspect.signature(SleeperAgent).parameters else {}
            team[day.sleeper_seat] = SleeperAgent(day.sleeper_seat, day.goal, strategy, random.Random(day_id), **kw)
        return day_id, world, team


def reward(srv, out, token=None):
    from sleeper.secrets import get_secret
    token = token or get_secret("VERIFY_TOKEN", None) or os.environ["VERIFY_TOKEN"]
    srv.finish()
    # Score the server's own in-memory final state. The file at `out` is only a copy: on the
    # local `make mcp` path the agent runs as the same OS user and can rewrite it.
    mem = getattr(srv, "final_state", None)
    state = mem() if callable(mem) else None
    src = ["--state", "-"] if state is not None else ["--state", out]
    r = subprocess.run([sys.executable, "-m", "sleeper.verifier", "--require-seat", *src], capture_output=True, text=True,
                       input=json.dumps(state) if state is not None else None, env={**os.environ, "VERIFY_TOKEN": token})
    try:
        d = json.loads(r.stdout)
    except ValueError:
        return "{}"
    d["seat_under_test"] = os.environ["SLEEPER_SEAT"]
    from sleeper.verifier import sign
    return json.dumps(sign(d, token))


def serve_reward(srv, out, token, httpd):
    httpd.serve_forever()


def make_httpd(srv, out, token, port):
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.headers.get("X-Verify-Token") != token or self.path != "/reward":
                self.send_response(404)
                self.end_headers()
                return
            body = reward(srv, out, token).encode()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    return HTTPServer(("0.0.0.0", port), H)


def main(argv=None):
    import argparse
    from sleeper.secrets import set_secret, take
    ap = argparse.ArgumentParser()
    ap.add_argument("--secrets-file", default=None)
    a = ap.parse_args(argv)
    sec = take("VERIFY_TOKEN", "SLEEPER_SALT", "SLEEPER_SEED", secrets_file=a.secrets_file)
    token = (sec.get("VERIFY_TOKEN") or "").strip()
    if not token:
        sys.exit("VERIFY_TOKEN is required")
    salt = (sec.get("SLEEPER_SALT") or "").strip()
    if not salt:
        sys.exit("SLEEPER_SALT is required")
    seed_raw = (sec.get("SLEEPER_SEED") or "").strip()
    if not seed_raw:
        sys.exit("SLEEPER_SEED is required")
    seed = int(seed_raw)
    set_secret(SLEEPER_SALT=salt)
    seat = os.environ["SLEEPER_SEAT"]
    out = os.environ.get("SLEEPER_OUT", "/srv/state.json")
    if os.path.isdir(out):
        sys.exit(f"SLEEPER_OUT must be a file path, got a directory: {out}")
    rport = int(os.environ.get("SIDECAR_REWARD_PORT", "8001"))
    mport = int(os.environ.get("SIDECAR_MCP_PORT", "8000"))
    for p in (mport, rport):
        with socket.socket() as t:
            if t.connect_ex(("127.0.0.1", p)) == 0:
                sys.exit(f"port {p} already in use (stale sidecar? pkill -f harbor.sidecar)")
    _, world, team = make_world_and_team(seed, seat, salt=salt)
    srv = build_server(world, seat, team, out, token=token)
    atexit.register(srv.finish)
    httpd = make_httpd(srv, out, token, rport)
    threading.Thread(target=serve_reward, args=(srv, out, token, httpd), daemon=True).start()
    srv.run(transport="streamable-http", host="0.0.0.0", port=mport)


if __name__ == "__main__":
    main()
