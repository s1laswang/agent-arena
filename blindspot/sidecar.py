"""Harbor sidecar: serves the AP seat over MCP (streamable-http :8000) and the
reward on :8001/reward, guarded by a per-task token that only the verifier
(tests/test.sh) knows. State and answer key live only in this container.

Env: BLINDSPOT_SEED, VERIFY_TOKEN, BLINDSPOT_STATE_OUT (default /srv/state.json),
     MCP_PORT (8000), REWARD_PORT (8001)
"""
from __future__ import annotations

import hmac
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .env import Env
from .mcp_server import build, dump
from .verify import score


def reward_server(env: Env, token: str, port: int, state_out: str):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            given = self.headers.get("X-Verify-Token", "")
            if self.path != "/reward" or not token or not hmac.compare_digest(given, token):
                self.send_response(404)
                self.end_headers()
                return
            env.world["ended"] = True  # finalise: no more changes after verification starts
            dump(env, state_out)
            s = score(env.state())
            body = json.dumps(s).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

    srv = ThreadingHTTPServer(("0.0.0.0", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def main():
    seed = int(os.environ.get("BLINDSPOT_SEED", "0"))
    token = os.environ.get("VERIFY_TOKEN", "")
    out = os.environ.get("BLINDSPOT_STATE_OUT", "/srv/state.json")
    env = Env(seed)
    dump(env, out)
    reward_server(env, token, int(os.environ.get("REWARD_PORT", "8001")), out)
    build(env, out).run("streamable-http", host="0.0.0.0", port=int(os.environ.get("MCP_PORT", "8000")))


if __name__ == "__main__":
    main()
