"""Frontier-agent red team (HANDOFF afterquery-canary). Fails on justSilas b4557e00, passes with patches/afterquery-canary/C-fixes.patch."""
import json
import os
import re
import statistics
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

from canary.baselines import BASELINES
from canary.env import Env
from canary.eval import run_episode
from canary.rules import TIERS

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("tier", ["easy", "medium", "hard"])
def test_c2_stop_early_is_zero_and_guessing_is_negative(tier):
    stop = [run_episode(Env(tier, s), BASELINES["stop_early"](seed=s)).score for s in range(900000, 900010)]
    guess = [run_episode(Env(tier, s), BASELINES["guess_day1"](seed=s)).score for s in range(900000, 900030)]
    assert stop == [0.0] * 10
    assert statistics.mean(guess) < 0


@pytest.mark.parametrize("tier", ["easy", "medium", "hard"])
def test_c2_ev_math_no_guess_is_positive_ev(tier):
    p = TIERS[tier]
    n, wrong = p.n_employees, -1.0
    for v in (1.0, 0.8, 0.5):                       # V only decays from 1.0
        for k in range(2, n + 1):                   # guess uniformly among k remaining suspects
            ev = v / k + wrong * (k - 1) / k        # = (V - (k-1)) / k
            assert ev <= 0 and (ev < 0 or (k == 2 and v == 1.0))  # 0 only for a coin flip between 2 before any leak
        # accusing is positive-EV only above the break-even posterior 1/(1+V) > 1/2: needs real evidence
        assert 1 / (1 + v) >= 0.5


def test_c1_ledger_mid_episode_reveals_no_leaks():
    from canary.mcp_server import Episode
    ep = Episode("medium", 900003, "template")
    for _ in range(5):
        ep.call("advance_day", {})
    mid = ep.ledger_payload()
    assert mid["ledger"] == [] and "V" not in mid and mid["score"] == 0.0
    emps = [e["id"] if isinstance(e, dict) else e for e in ep.call("list_employees", {}).data["employees"]]
    ep.call("accuse", {"employee": emps[0]})
    end = ep.ledger_payload()
    assert end["done"] and end["ledger"] and "V" in end


def test_c1_make_mcp_consumes_secret_files(tmp_path):
    ep, tok = tmp_path / "episode.json", tmp_path / "ledger_token"
    ep.write_text(json.dumps({"tier": "medium", "seed": 900003})); tok.write_text("t" * 24)
    os.chmod(ep, 0o600); os.chmod(tok, 0o600)
    env = {k: v for k, v in os.environ.items() if not k.startswith("CANARY_")}
    env.update(CANARY_EPISODE_FILE=str(ep), CANARY_LEDGER_TOKEN_FILE=str(tok), CANARY_PORT="8798", CANARY_CONSUME_SECRET_FILES="1")
    p = subprocess.Popen([sys.executable, "-m", "canary.mcp_server"], env=env, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(60):
            time.sleep(0.5)
            try:
                urllib.request.urlopen("http://127.0.0.1:8798/ledger?token=" + "t" * 24, timeout=2).read()
                break
            except Exception:  # noqa: BLE001
                continue
        assert not ep.exists() and not tok.exists(), "secret files still readable by the same uid"
    finally:
        p.kill()
