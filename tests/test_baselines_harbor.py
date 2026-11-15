import asyncio
import json
import subprocess
import sys

import pytest

from harbor.sidecar import make_world_and_team
from lab.run import build_team, day_for, play_day
from sleeper.baselines import register
from sleeper.company import BUDGET
from sleeper.mcp_server import build_server
from sleeper.scripted import NoopAgent

import os

DAYS = range(1000, 1010 if os.environ.get("SLEEPER_SLOW") == "1" else 1003)
SEATS = ("finance_ap", "controller")
FRACS = (0.25, 0.5)


class Seat:
    def __init__(self, srv, cap):
        self.srv, self.cap, self.n = srv, cap, 0

    def __call__(self, name, args=None):
        if self.cap is not None and self.n >= self.cap and name != "end_turn":
            return {"ok": False, "error": "stopped"}
        self.n += name != "end_turn"
        r = asyncio.run(self.srv.call_tool(name, args or {}))
        return r.structured_content or json.loads(r.content[0].text)


def judge(day_id, seat, agent_name, cap, tmp_path):
    out = tmp_path / f"{seat}-{day_id}-{agent_name}-{cap}.json"
    _, world, team = make_world_and_team(day_id, seat)
    srv = build_server(world, seat, team, str(out))
    call = Seat(srv, cap)
    agent = NoopAgent() if agent_name == "noop" else build_team("oracle", world.day, 0)[seat]
    for _ in range(world.last_tick + 50):
        if out.exists():
            break
        agent.turn(seat, {"tick": world.tick}, [], call)
        call("end_turn", {})
    srv.finish()
    r = subprocess.run([sys.executable, "-m", "sleeper.verifier", "--require-seat", "--state", str(out)], capture_output=True, text=True, env={**os.environ, "SLEEPER_SEAT": seat, "SLEEPER_ALLOW_UNSIGNED": "1"})  # unsigned play_day state
    return json.loads(r.stdout), call.n


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("SLEEPER_TEAM", "oracle")
    monkeypatch.delenv("SLEEPER_SEAT", raising=False)
    register()


@pytest.mark.parametrize("seat", SEATS)
def test_do_nothing_zero_via_judge_path(seat, tmp_path):
    bad = [d for d in DAYS if judge(d, seat, "noop", None, tmp_path)[0]["reward"] != 0]
    assert bad == []


@pytest.mark.parametrize("frac", FRACS)
@pytest.mark.parametrize("seat", SEATS)
def test_stop_early_zero_via_judge_path(seat, frac, tmp_path):
    bad = []
    for d in DAYS:
        full = judge(d, seat, "oracle", None, tmp_path)[1]
        r, n = judge(d, seat, "oracle", int(frac * full), tmp_path)
        if r["reward"] != 0:
            bad.append((d, n, r["reward"], r["harm"], r["tickets_done"], r["tickets_total"]))
    assert bad == []


@pytest.mark.parametrize("seat", SEATS)
def test_oracle_one_via_judge_path_and_matches_play_day(seat, tmp_path):
    diff = []
    for d in DAYS:
        j, _ = judge(d, seat, "oracle", None, tmp_path)
        p = play_day("oracle", "oracle", seat, d, 0)[0]
        if j["reward"] != 1 or p["reward"] != j["reward"]:
            diff.append((d, j["reward"], p["reward"], j.get("harm"), p["harm"]))
    assert diff == []
