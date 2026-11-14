"""Canary browser game (game/, WS6): seed rules, no hidden calls, reveal only at the end, and
browser (Pyodide) == Python parity for the same seed + actions. Owner: HARNESS."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "game"))
import canary_game as G  # noqa: E402

from canary.rules import HELDOUT_SEEDS, JUDGE_SEEDS  # noqa: E402


@pytest.mark.parametrize("seed", [min(JUDGE_SEEDS), max(JUDGE_SEEDS), min(HELDOUT_SEEDS), 100000, 0, 2999, 10000,
                                  "3000.0", "3e3", None, "abc"])
def test_benchmark_and_bad_seeds_are_refused(seed):
    with pytest.raises(ValueError):
        G.Game(seed)


def test_spec_makes_no_tool_call_and_reveal_waits_for_the_end():
    g = G.Game(3000)
    spec = json.loads(g.spec_json())
    assert spec["tier"] == "medium" and spec["seed"] == 3000 and len(spec["tools"]) == 13
    assert g.env.history == []                       # the page never calls tools on its own
    assert "error" in json.loads(g.reveal_json())    # no truth before the episode is over
    assert g.env._world.mole not in json.dumps(spec["tools"])  # tool specs carry no world facts


def _solver_actions(seed: int) -> list[list]:
    from canary.env import Env
    from canary.solver.policy import SolverPolicy
    env = Env(G.TIER, seed)
    pol = SolverPolicy()
    pol.reset(env.tools_spec(), env.instruction())
    acts = []
    while not env.done:
        tool, args = pol.act(env.history)
        acts.append([tool, args])
        env.call(tool, args)
    return acts


def test_full_game_and_reveal():
    g = G.Game(3001)
    for tool, args in _solver_actions(3001):
        out = json.loads(g.call_json(tool, json.dumps(args)))
    assert out["done"]
    r = json.loads(g.reveal_json())
    assert r["you"]["score"] == r["solver"]["score"]          # same actions as the solver -> same score
    assert r["mole"] == g.env._world.mole and r["you"]["tool_calls"] == len(g.actions)


def test_bad_json_args_do_not_crash_or_count_as_a_call():
    g = G.Game(3000)
    out = json.loads(g.call_json("interview", "{not json"))
    assert out["ok"] is False and g.env.history == [] and g.actions == []


def test_replay_is_deterministic_in_python():
    acts = _solver_actions(3002)
    assert G.replay(3002, acts) == G.replay(3002, acts)


def _pyodide_dir() -> Path | None:
    d = os.environ.get("CANARY_PYODIDE_DIR")
    if d and (Path(d) / "pyodide.mjs").exists():
        return Path(d)
    local = ROOT / "game" / "node_modules" / "pyodide"
    return local if (local / "pyodide.mjs").exists() else None


@pytest.mark.skipif(shutil.which("node") is None or _pyodide_dir() is None,
                    reason="needs node + pyodide (npm install pyodide@0.27.7; set CANARY_PYODIDE_DIR)")
@pytest.mark.parametrize("seed,kind", [(3000, "solver"), (3003, "mixed")])
def test_browser_pyodide_matches_python_for_same_seed_and_actions(tmp_path, seed, kind):
    sys.path.insert(0, str(ROOT / "game"))
    import build as game_build
    site = tmp_path / "site"
    game_build.build(site)                                     # test exactly what ships
    acts = _solver_actions(seed)
    if kind == "mixed":                                        # invalid calls + an early wrong-ish accusation path
        acts = [["interview", {"employee": "e01", "topic": "workload"}], ["accuse", {"employee": ["e01"]}],
                ["list_documents", {"day_from": 0}]] + acts
    rec = tmp_path / "actions.json"
    rec.write_text(json.dumps({"seed": seed, "actions": acts}))
    out = subprocess.run(["node", str(ROOT / "game" / "tests" / "parity.mjs"), str(_pyodide_dir()), str(site / "py"),
                          str(rec)], capture_output=True, text=True, timeout=300)
    assert out.returncode == 0, out.stderr[-2000:]
    browser = json.loads(out.stdout.strip().splitlines()[-1])
    python = json.loads(json.dumps(G.replay(seed, acts), sort_keys=True))
    assert browser == python and browser["done"]
