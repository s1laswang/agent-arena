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


def effective_id(seed, seat=None):
    import hashlib
    salt = os.environ.get("SLEEPER_SALT", "")
    return int(hashlib.sha256(f"{salt}:{seed}".encode()).hexdigest(), 16) % 100000 if salt else seed


def make_world_and_team(seed, seat):
    import inspect
    import random
    from lab.run import build_team, day_for
    day_id = effective_id(seed)
    day, strategy, _, _ = day_for(day_id, seat)
    team = build_team(os.environ.get("SLEEPER_TEAM", "staff"), day, 0)
    if day.sleeper_seat and strategy:
        from agents.sleeper_agent import SleeperAgent
        kw = {"ticks": day.ticks} if "ticks" in inspect.signature(SleeperAgent).parameters else {}
        team[day.sleeper_seat] = SleeperAgent(day.sleeper_seat, day.goal, strategy, random.Random(day_id), **kw)
    return day_id, World(day), team


def reward(srv, out):
    srv.finish()
    r = subprocess.run([sys.executable, "-m", "sleeper.verifier", "--state", out], capture_output=True, text=True)
    try:
        d = json.loads(r.stdout)
    except ValueError:
        return "{}"
    d["seat_under_test"] = os.environ["SLEEPER_SEAT"]
    return json.dumps(d)


def serve_reward(srv, out, token, httpd):
    httpd.serve_forever()


def make_httpd(srv, out, token, port):
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.headers.get("X-Verify-Token") != token or self.path != "/reward":
                self.send_response(404)
                self.end_headers()
                return
            body = reward(srv, out).encode()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    return HTTPServer(("0.0.0.0", port), H)


def main():
    seed = int(os.environ["SLEEPER_SEED"])
    seat = os.environ["SLEEPER_SEAT"]
    out = os.environ.get("SLEEPER_OUT", "/srv/state.json")
    token = os.environ["VERIFY_TOKEN"]
    if os.path.isdir(out):
        sys.exit(f"SLEEPER_OUT must be a file path, got a directory: {out}")
    rport = int(os.environ.get("SIDECAR_REWARD_PORT", "8001"))
    mport = int(os.environ.get("SIDECAR_MCP_PORT", "8000"))
    for p in (mport, rport):
        with socket.socket() as t:
            if t.connect_ex(("127.0.0.1", p)) == 0:
                sys.exit(f"port {p} already in use (stale sidecar? pkill -f harbor.sidecar)")
    _, world, team = make_world_and_team(seed, seat)
    srv = build_server(world, seat, team, out)
    atexit.register(srv.finish)
    httpd = make_httpd(srv, out, token, rport)
    threading.Thread(target=serve_reward, args=(srv, out, token, httpd), daemon=True).start()
    srv.run(transport="streamable-http", host="0.0.0.0", port=mport)


if __name__ == "__main__":
    main()
