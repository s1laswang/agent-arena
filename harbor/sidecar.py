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
    salt = os.environ.get("SLEEPER_SALT", "") if salt is None else salt
    return int(hashlib.sha256(f"{salt}:{seed}".encode()).hexdigest(), 16) % DAY_SPACE if salt else seed


def make_world_and_team(seed, seat, salt=None):
    import inspect
    import random
    from lab.run import build_team, day_for
    day_id = effective_id(seed, salt=salt)
    day, strategy, _, _ = day_for(day_id, seat)
    name = os.environ.get("SLEEPER_TEAM", "procedure")
    if name in ("procedure", "seat"):
        from sleeper.scripted import seat_team
        return day_id, World(day), seat_team(day, seat, day_id, strategy)
    team = build_team(name, day, 0)
    if day.sleeper_seat and strategy:
        from agents.sleeper_agent import SleeperAgent
        kw = {"ticks": day.ticks} if "ticks" in inspect.signature(SleeperAgent).parameters else {}
        team[day.sleeper_seat] = SleeperAgent(day.sleeper_seat, day.goal, strategy, random.Random(day_id), **kw)
    return day_id, World(day), team


def reward(srv, out, token=None):
    token = token or os.environ["VERIFY_TOKEN"]
    srv.finish()
    r = subprocess.run([sys.executable, "-m", "sleeper.verifier", "--require-seat", "--state", out], capture_output=True, text=True,
                       env={**os.environ, "VERIFY_TOKEN": token})
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


def main():
    from sleeper.secrets import take
    sec = take("VERIFY_TOKEN", "SLEEPER_SALT", "SLEEPER_SEED")
    seed = int(sec["SLEEPER_SEED"])
    seat = os.environ["SLEEPER_SEAT"]
    out = os.environ.get("SLEEPER_OUT", "/srv/state.json")
    token = sec["VERIFY_TOKEN"]
    if not token:
        sys.exit("VERIFY_TOKEN is required")
    if os.path.isdir(out):
        sys.exit(f"SLEEPER_OUT must be a file path, got a directory: {out}")
    rport = int(os.environ.get("SIDECAR_REWARD_PORT", "8001"))
    mport = int(os.environ.get("SIDECAR_MCP_PORT", "8000"))
    for p in (mport, rport):
        with socket.socket() as t:
            if t.connect_ex(("127.0.0.1", p)) == 0:
                sys.exit(f"port {p} already in use (stale sidecar? pkill -f harbor.sidecar)")
    _, world, team = make_world_and_team(seed, seat, salt=sec["SLEEPER_SALT"] or "")
    srv = build_server(world, seat, team, out, token=token)
    atexit.register(srv.finish)
    httpd = make_httpd(srv, out, token, rport)
    threading.Thread(target=serve_reward, args=(srv, out, token, httpd), daemon=True).start()
    srv.run(transport="streamable-http", host="0.0.0.0", port=mport)


if __name__ == "__main__":
    main()
