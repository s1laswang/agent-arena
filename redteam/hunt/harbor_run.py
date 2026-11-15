"""Judge path end to end: start harbor.sidecar (secrets file, salt, token), play a policy ONLY over MCP HTTP,
then GET /reward with X-Verify-Token like harbor.collect does.
Usage: harbor_run.py SEAT START N {intfilter|trusting|noop} MCP_PORT [SALT]"""
import asyncio
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(__file__))
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from policies import TicketPolicy

seat, start, n, mode, port = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4], int(sys.argv[5])
salt = sys.argv[6] if len(sys.argv) > 6 else os.urandom(16).hex()
token = os.urandom(16).hex()
import tempfile
TMP = tempfile.mkdtemp(prefix="hunt-")


class DayOver(Exception):
    pass


def start_sidecar(seed):
    sf = os.path.join(TMP, f"sec-{port}.json")
    fd = os.open(sf, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"SLEEPER_SALT": salt, "SLEEPER_SEED": str(seed), "VERIFY_TOKEN": token}, f)
    env = {k: v for k, v in os.environ.items() if k not in ("VERIFY_TOKEN", "SLEEPER_SALT", "SLEEPER_SEED")}
    env.update(SLEEPER_SECRETS_FILE=sf, SLEEPER_SEAT=seat, SLEEPER_OUT=os.path.join(TMP, f"state-{port}.json"),
               SIDECAR_MCP_PORT=str(port), SIDECAR_REWARD_PORT=str(port + 1), PYTHONPATH=os.getcwd(),
               GEMINI_API_KEY="", SLEEPER_OFFLINE="1")
    p = subprocess.Popen([sys.executable, "-m", "harbor.sidecar"], cwd=os.getcwd(), env=env,
                         stdout=open(os.path.join(TMP, f"sidecar-{port}.log"), "w"), stderr=subprocess.STDOUT)
    for _ in range(150):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return p
        time.sleep(0.2)
    raise RuntimeError("sidecar did not start")


async def play(url):
    async with streamable_http_client(url) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            loop = asyncio.get_running_loop()

            async def acall(name, args):
                res = await s.call_tool(name, args)
                return json.loads(res.content[0].text) if res.content else {}

            def call(name, args=None):
                out = asyncio.run_coroutine_threadsafe(acall(name, args or {}), loop).result()
                if isinstance(out, dict) and out.get("error") == "day over":
                    raise DayOver
                return out

            def rounds():
                if mode == "noop":
                    return
                leak = {"leakpad": "pad", "leakplain": "plain"}.get(mode)
                pol = TicketPolicy(int_filter=(mode in ("intfilter", "leakpad", "leakplain")), leak=leak, seat=seat)
                try:
                    for _ in range(400):
                        pol.turn(call)
                except DayOver:
                    pass

            await loop.run_in_executor(None, rounds)


tot = 0
for seed in range(start, start + n):
    p = start_sidecar(seed)
    try:
        asyncio.run(play(f"http://127.0.0.1:{port}/mcp"))
        req = urllib.request.Request(f"http://127.0.0.1:{port + 1}/reward", headers={"X-Verify-Token": token})
        d = json.loads(urllib.request.urlopen(req, timeout=120).read())
    finally:
        p.send_signal(signal.SIGTERM)
        try:
            p.wait(10)
        except subprocess.TimeoutExpired:
            p.kill()
    tot += d.get("reward", 0)
    print(json.dumps({"seed": seed, "mode": mode, "reward": d.get("reward"), "done": f"{d.get('tickets_done')}/{d.get('tickets_total')}",
                      "harm": (d.get("harm") or [])[:8], "signed": "sig" in d}), flush=True)
print("SUMMARY harbor-path", seat, mode, f"{tot}/{n}", "salt", salt[:6] + "...")
