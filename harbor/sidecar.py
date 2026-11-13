import atexit
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from sleeper.company import World
from sleeper.mcp_server import build_server


def effective_id(seed, seat):
    import hashlib
    from lab.run import day_for
    salt = os.environ.get("SLEEPER_SALT", "")
    k = int(hashlib.sha256(f"{salt}:{seed}".encode()).hexdigest(), 16) % 100000 if salt else seed
    while day_for(k)[0].sleeper_seat == seat:
        k += 1
    return k


def make_world_and_team(seed, seat):
    import random
    from lab.run import build_team, day_for
    day_id = effective_id(seed, seat)
    day, strategy, _ = day_for(day_id)
    team = build_team(os.environ.get("SLEEPER_TEAM", "staff"), day, 0)
    if day.sleeper_seat and strategy:
        from agents.sleeper_agent import SleeperAgent
        team[day.sleeper_seat] = SleeperAgent(day.sleeper_seat, day.goal, strategy, random.Random(day_id * 1000))
    return day_id, World(day), team


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
    _, world, team = make_world_and_team(seed, seat)
    srv = build_server(world, seat, team, out)
    atexit.register(srv.finish)
    threading.Thread(target=serve_reward, args=(srv, out, token, int(os.environ.get("SIDECAR_REWARD_PORT", "8001"))), daemon=True).start()
    srv.run(transport="streamable-http", host="0.0.0.0", port=int(os.environ.get("SIDECAR_MCP_PORT", "8000")))


if __name__ == "__main__":
    main()
