import atexit
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from sleeper.company import World
from sleeper.mcp_server import build_server


def pick(seed, seat):
    import hashlib
    from sleeper.daymix import day_spec
    salt = os.environ.get("SLEEPER_SALT", "")
    eff = int(hashlib.sha256(f"{salt}:{seed}".encode()).hexdigest(), 16) % 100000 if salt else seed
    return day_spec(eff, seat)


def make_world(seed, spec):
    from sleeper.tickets import make_day
    return World(make_day(seed, spec["sleeper_seat"], spec["goal"]))


def make_team(world, seed, spec):
    team = None
    if os.environ.get("SLEEPER_TEAM", "staff") == "staff":
        try:
            from agents.staff import make_team as mk
            team = mk(world.day, seed)
        except Exception:
            team = None
    if team is None:
        from sleeper.scripted import OracleAgent, make_team as mk
        team = mk(OracleAgent)
    if spec["sleeper_seat"] and os.environ.get("SLEEPER_TEAM", "staff") == "staff":
        from agents.sleeper_agent import SleeperAgent
        team[spec["sleeper_seat"]] = SleeperAgent(spec["sleeper_seat"], spec["goal"], spec["strategy"])
    return team


def reward(srv, out):
    srv.finish()
    r = subprocess.run([sys.executable, "-m", "sleeper.verifier", "--state", out], capture_output=True, text=True)
    return r.stdout.strip() or "{}"


def serve_reward(srv, out, token, port):
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.headers.get("X-Verify-Token") != token or self.path != "/reward":
                self.send_response(404)
                self.end_headers()
                return
            r = reward(srv, out)
            body = r.encode()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    HTTPServer(("0.0.0.0", port), H).serve_forever()


def main():
    seed = int(os.environ["SLEEPER_SEED"])
    seat = os.environ["SLEEPER_SEAT"]
    out = os.environ.get("SLEEPER_OUT", "/srv/state.json")
    token = os.environ["VERIFY_TOKEN"]
    spec = pick(seed, seat)
    world = make_world(seed, spec)
    srv = build_server(world, seat, make_team(world, seed, spec), out)
    atexit.register(srv.finish)
    threading.Thread(target=serve_reward, args=(srv, out, token, int(os.environ.get("SIDECAR_REWARD_PORT", "8001"))), daemon=True).start()
    srv.run(transport="streamable-http", host="0.0.0.0", port=int(os.environ.get("SIDECAR_MCP_PORT", "8000")))


if __name__ == "__main__":
    main()
