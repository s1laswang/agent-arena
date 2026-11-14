"""canary.mcp_server over real streamable HTTP (HARNESS).

Starts `python -m canary.mcp_server` in a subprocess on a free port and talks to it with the official
mcp client, exactly like OpenCode/Codex would.
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

import pytest

from canary.baselines import DoNothing, StopEarly
from canary.env import Env
from canary.eval import run_episode
from canary.mcp_server import play_policy
from canary.solver.policy import SolverPolicy

LEDGER, ADMIN = "test-ledger-token", "test-admin-token"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _get(url: str):
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, None


def _post(url: str, body: dict):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, None


class Srv:
    def __init__(self, tier="easy", seed=0, allow_dev=True):
        self.port = _free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        self.url = self.base + "/mcp"
        env = dict(os.environ, CANARY_HOST="127.0.0.1", CANARY_PORT=str(self.port), CANARY_TIER=tier,
                   CANARY_SEED=str(seed), CANARY_LEDGER_TOKEN=LEDGER, CANARY_ADMIN_TOKEN=ADMIN)
        env.pop("CANARY_ALLOW_DEV", None)
        if allow_dev:
            env["CANARY_ALLOW_DEV"] = "1"
        self.proc = subprocess.Popen([sys.executable, "-m", "canary.mcp_server"], env=env,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for _ in range(100):
            try:
                if _get(self.base + "/healthz")[0] == 200:
                    return
            except Exception:
                pass
            if self.proc.poll() is not None:
                break
            time.sleep(0.1)
        self.stop()
        raise RuntimeError("mcp server did not start: " + (self.proc.stdout.read() if self.proc.stdout else ""))

    def reset(self, tier: str, seed: int):
        assert _post(f"{self.base}/admin/reset?token={ADMIN}", {"tier": tier, "seed": seed})[0] == 200

    def ledger(self):
        code, body = _get(f"{self.base}/ledger?token={LEDGER}")
        assert code == 200
        return body

    def stop(self):
        self.proc.terminate()
        try:
            out, _ = self.proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            out, _ = self.proc.communicate()
        return out or ""


@pytest.fixture(scope="module")
def srv():
    s = Srv("easy", 0)
    yield s
    s.stop()


def _client_call(url: str, calls: list[tuple[str, dict]]):
    from mcp import Client

    async def go():
        out = []
        async with Client(url) as c:
            for name, args in calls:
                r = await c.call_tool(name, args)
                out.append(json.loads(r.content[0].text))
        return out
    return asyncio.run(go())


def test_list_tools_matches_env_spec(srv):
    from mcp import Client

    async def go():
        async with Client(srv.url) as c:
            return (await c.list_tools()).tools, c.instructions
    tools, instructions = asyncio.run(go())
    spec = Env("easy", 0).tools_spec()
    assert [t.name for t in tools] == [s["name"] for s in spec]
    for t, s in zip(tools, spec):
        assert t.description == s["description"]
        assert t.input_schema == s["input_schema"]
    assert instructions == Env("easy", 0).instruction()


@pytest.mark.parametrize("policy_cls,tier,seed", [(DoNothing, "easy", 5), (StopEarly, "medium", 7),
                                                  (StopEarly, "easy", 1), (SolverPolicy, "hard", 3)])
def test_episode_over_mcp_matches_in_process(srv, policy_cls, tier, seed):
    srv.reset(tier, seed)
    mk = (lambda: policy_cls()) if policy_cls is SolverPolicy else (lambda: policy_cls(seed=seed))
    hist = asyncio.run(play_policy(srv.url, mk()))
    local = run_episode(Env(tier, seed), mk())
    led = srv.ledger()
    assert led["done"] and led["score"] == local.score
    assert led["end_reason"] == local.end_reason and len(hist) == len(local.steps)
    assert [h.result for h in hist] == [s.result for s in local.steps]
    if policy_cls is DoNothing:
        assert led["score"] == 0.0 and led["end_reason"] == "horizon"


def test_errors_come_from_env_unchanged(srv):
    srv.reset("easy", 2)
    env = Env("easy", 2)
    calls = [("interview", {"employee": ["e01", "e02"], "topic": "workload"}), ("accuse", {"employee": "*"}),
             ("no_such_tool", {}), ("status", {"bogus": 1}), ("read_access_logs", {"day_from": 1, "day_to": 99})]
    remote = _client_call(srv.url, calls)
    for (name, args), r in zip(calls, remote):
        loc = env.call(name, args)
        assert r == {"ok": loc.ok, "data": loc.data, "error": loc.error}
        assert not r["ok"]


def test_no_seed_or_mole_in_tool_output(srv):
    srv.reset("medium", 4242)
    env = Env("medium", 4242)
    mole = env._world.mole
    out = _client_call(srv.url, [("status", {}), ("list_employees", {}), ("advance_day", {}),
                                 ("check_leak_feed", {}), ("accuse", {"employee": "e00"}), ("status", {})])
    text = json.dumps(out)
    assert "4242" not in text and str(env._world.world_seed) not in text
    accuse = out[4]
    assert accuse == {"ok": True, "data": {"accused": "e00", "episode_over": True}, "error": None}
    assert "correct" not in text and (mole == "e00" or mole not in json.dumps(accuse))


def test_ledger_requires_token(srv):
    assert _get(f"{srv.base}/ledger")[0] == 403
    assert _get(f"{srv.base}/ledger?token=wrong")[0] == 403
    assert _get(f"{srv.base}/ledger?token={LEDGER}")[0] == 200
    assert _post(f"{srv.base}/admin/reset", {"tier": "easy", "seed": 1})[0] == 403
    assert _post(f"{srv.base}/admin/reset?token=wrong", {"tier": "easy", "seed": 1})[0] == 403


def test_parallel_accuse_records_exactly_one(srv):
    srv.reset("medium", 9)
    ids = [f"e{i:02d}" for i in range(8)]
    results: dict[str, dict] = {}

    def worker(e):
        results[e] = _client_call(srv.url, [("accuse", {"employee": e})])[0]

    threads = [threading.Thread(target=worker, args=(e,)) for e in ids]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    oks = [e for e, r in results.items() if r["ok"]]
    assert len(results) == 8 and len(oks) == 1
    assert all(r["error"] == "episode over" for e, r in results.items() if e != oks[0])
    led = srv.ledger()
    accused = [x for x in led["ledger"] if x["event"] == "accused"]
    assert len(accused) == 1 and accused[0]["detail"]["employee"] == oks[0] == led["accused"]


def test_fresh_process_from_env_vars_matches():
    s = Srv("hard", 17)
    try:
        hist = asyncio.run(play_policy(s.url, StopEarly(seed=17)))
        local = run_episode(Env("hard", 17), StopEarly(seed=17))
        assert s.ledger()["score"] == local.score and [h.result for h in hist] == [x.result for x in local.steps]
    finally:
        log = s.stop()
    assert "seed" not in log.lower()  # the seed is never logged


def test_dev_seeds_refused_without_allow_dev():
    port = _free_port()
    env = dict(os.environ, CANARY_PORT=str(port), CANARY_TIER="easy", CANARY_SEED="5")
    env.pop("CANARY_ALLOW_DEV", None)
    p = subprocess.run([sys.executable, "-m", "canary.mcp_server"], env=env, capture_output=True, text=True, timeout=60)
    assert p.returncode == 2 and "refusing to start" in p.stderr and "5" not in p.stderr.replace("CANARY", "")


def test_judge_seed_served_and_dev_reset_refused():
    s = Srv("medium", 900_003, allow_dev=False)
    try:
        assert _get(s.base + "/healthz")[0] == 200
        out = _client_call(s.url, [("status", {})])[0]
        assert out["ok"] and "900003" not in json.dumps(out)
        assert _post(f"{s.base}/admin/reset?token={ADMIN}", {"tier": "easy", "seed": 1})[0] == 400
        assert _post(f"{s.base}/admin/reset?token={ADMIN}", {"tier": "easy", "seed": 800_001})[0] == 200
    finally:
        s.stop()
