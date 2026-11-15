from __future__ import annotations

import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import tokenize
from pathlib import Path

import pytest

from canary.env import Env
from canary.eval import run_episode
from canary.rules import HELDOUT_SEEDS, JUDGE_SEEDS, TRAIN_SEEDS
from canary.solver.policy import SolverPolicy

ROOT = Path(__file__).resolve().parents[1]
PY_MOD_PATH = ROOT / "docs" / "arena" / "solver_live.py"
JS_MOD_PATH = ROOT / "docs" / "arena" / "solver_live.js"
THIS_TEST_PATH = Path(__file__).resolve()

EMP_ID_RE = re.compile(r"\be\d{2}\b")
FORBIDDEN_PRE_SUBSTRINGS = (
    '"mole"',
    '"true_mole"',
    '"decoy"',
    '"correct"',
    '"true_v"',
    '"is_canary"',
    '"accused"',
    '"score"',
    '"daily_trace"',
)


def _load_solver_live():
    os.environ["GOOGLE_API_KEY"] = ""
    os.environ["GEMINI_API_KEY"] = ""
    os.environ["OPENAI_API_KEY"] = ""
    spec = importlib.util.spec_from_file_location("arena_solver_live", PY_MOD_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["arena_solver_live"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_hygiene_zero_comments_zero_dashes_and_no_world_access():
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    slash_slash = chr(47) * 2
    slash_star = chr(47) + chr(42)

    for path in (PY_MOD_PATH, JS_MOD_PATH, THIS_TEST_PATH):
        assert path.is_file(), f"missing {path}"
        text = path.read_text(encoding="utf-8")
        assert em_dash not in text, f"em dash found in {path.name}"
        assert en_dash not in text, f"en dash found in {path.name}"

    for py_path in (PY_MOD_PATH, THIS_TEST_PATH):
        src = py_path.read_text(encoding="utf-8")
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert comments == [], f"python comments found in {py_path.name}: {comments[:3]}"

    py_src = PY_MOD_PATH.read_text(encoding="utf-8")
    assert "_world" not in py_src
    assert ".mole" not in py_src
    assert ".decoy" not in py_src

    js_src = JS_MOD_PATH.read_text(encoding="utf-8")
    assert slash_slash not in js_src
    assert slash_star not in js_src


def test_seed_and_tier_guards():
    mod = _load_solver_live()

    for tier in ("easy", "medium", "hard"):
        for valid_seed in (0, 1, 15, 29, 3000, 4321, 9999):
            assert mod.validate_tier_and_seed(tier, valid_seed) == (tier, valid_seed)

    rejected_seeds = [
        -1,
        30,
        31,
        59,
        100,
        2999,
        10000,
        JUDGE_SEEDS[0],
        JUDGE_SEEDS[-1],
        HELDOUT_SEEDS[0],
        TRAIN_SEEDS[0],
        True,
        False,
        None,
        3000.0,
        0.0,
        "0",
        "3000",
        "3000.0",
        [3000],
    ]
    for bad_seed in rejected_seeds:
        with pytest.raises(ValueError):
            mod.validate_tier_and_seed("hard", bad_seed)
        with pytest.raises(ValueError):
            mod.LiveSolverSession("hard", bad_seed)

    for bad_tier in ("", "hard_forge", "hard_rl", "extreme", None, 1, True):
        with pytest.raises(ValueError):
            mod.validate_tier_and_seed(bad_tier, 3000)

    sess = mod.LiveSolverSession("easy", 0)
    for bad_day in (True, False, None, 1.5, "1"):
        with pytest.raises(ValueError):
            sess.get_solver_day_state(bad_day, False)


@pytest.mark.parametrize(
    ("tier", "seed"),
    [
        ("easy", 0),
        ("medium", 0),
        ("medium", 20),
        ("hard", 0),
        ("hard", 4),
        ("hard", 15),
        ("hard", 26),
        ("medium", 3000),
        ("hard", 3000),
        ("hard", 3001),
    ],
)
def test_pre_end_zero_leak_invariant_and_progression(tier: str, seed: int):
    mod = _load_solver_live()
    session = mod.LiveSolverSession(tier, seed)
    world = Env(tier, seed)._world
    true_mole = world.mole
    true_decoy = world.decoy

    prev_canaries = 0
    prev_interviews = 0
    prev_calls = 0

    for human_day in range(1, 26):
        for non_true_done in (False, 0, 1, "true", None):
            state = session.get_solver_day_state(human_day, non_true_done)
            assert set(state.keys()) == set(mod.PRE_END_KEYS)

            raw_json = session.get_solver_day_state_json(human_day, non_true_done)
            assert true_mole not in raw_json
            if true_decoy is not None:
                assert true_decoy not in raw_json
            assert EMP_ID_RE.search(raw_json) is None
            for forbidden in FORBIDDEN_PRE_SUBSTRINGS:
                assert forbidden not in raw_json

            if human_day < session.final_day:
                assert state["day"] == human_day
                assert state["status"] == "hunting"
                assert state["sealed_day"] is None
            else:
                assert state["day"] == session.final_day
                assert state["status"] == "sealed_accusation"
                assert state["sealed_day"] == session.final_day

            assert 0.0 <= state["visible_V"] <= 1.0
            assert 0.0 <= state["top_posterior_prob"] <= 1.0 + 1e-12
            assert state["entropy_bits"] >= 0.0

        day_state = session.get_solver_day_state(human_day, False)
        assert day_state["canaries_planted"] >= prev_canaries
        assert day_state["interviews_done"] >= prev_interviews
        assert day_state["tool_calls_so_far"] >= prev_calls
        prev_canaries = day_state["canaries_planted"]
        prev_interviews = day_state["interviews_done"]
        prev_calls = day_state["tool_calls_so_far"]

    clamped_low = session.get_solver_day_state(0, False)
    assert clamped_low["day"] == 1


@pytest.mark.parametrize(
    ("tier", "seed", "expected_day", "expected_score"),
    [
        ("easy", 0, None, None),
        ("easy", 3000, None, None),
        ("medium", 0, None, None),
        ("medium", 4, None, None),
        ("medium", 20, 14, 0.0),
        ("medium", 3000, None, None),
        ("hard", 0, None, None),
        ("hard", 4, 5, 0.73),
        ("hard", 15, 9, -1.0),
        ("hard", 26, 7, 0.69),
        ("hard", 3000, None, None),
        ("hard", 3001, None, None),
    ],
)
def test_post_end_bit_identical_parity_with_canary_eval(
    tier: str,
    seed: int,
    expected_day: int | None,
    expected_score: float | None,
):
    mod = _load_solver_live()
    ref = run_episode(Env(tier, seed), SolverPolicy(tier))
    sess = mod.start_solver_session(tier, seed)
    revealed = mod.get_solver_day_state(1, True, tier=tier, seed=seed)

    assert revealed["status"] == "revealed"
    assert revealed["accused"] == ref.accused
    assert revealed["correct"] is bool(ref.correct)
    assert revealed["final_day"] == ref.final_day
    assert revealed["tool_calls"] == len(ref.steps)
    assert revealed["tool_calls_so_far"] == len(ref.steps)
    assert abs(revealed["score"] - ref.score) < 1e-12
    assert len(revealed["daily_trace"]) == ref.final_day
    assert sess.get_solver_day_state(99, True) == revealed

    if expected_day is not None:
        assert revealed["final_day"] == expected_day
    if expected_score is not None:
        assert abs(revealed["score"] - expected_score) < 1e-12


def test_js_es_module_window_global_and_pyodide_bridge():
    mod = _load_solver_live()
    sess_26 = mod.LiveSolverSession("hard", 26)
    fixtures = {
        "d3_locked": sess_26.get_solver_day_state_json(3, False),
        "d9_locked": sess_26.get_solver_day_state_json(9, False),
        "d9_unlocked": sess_26.get_solver_day_state_json(9, True),
    }

    node_script = """
import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";

globalThis.window = {};
const modUrl = pathToFileURL(process.env.JS_MOD_PATH).href;
const ns = await import(modUrl);

assert.equal(typeof window.CanarySolverLive, "object");
assert.equal(ns.default, window.CanarySolverLive);
assert.deepEqual(ns.ALLOWED_TIERS, ["easy", "medium", "hard"]);

assert.deepEqual(ns.validateTierAndSeed("hard", 26), { tier: "hard", seed: 26 });
assert.deepEqual(ns.validateTierAndSeed("medium", 3000), { tier: "medium", seed: 3000 });
for (const bad of [-1, 30, 2999, 10000, 900000, 800000, 100000, "3000", "3000.0", 3.5, true, null]) {
  assert.throws(() => ns.validateTierAndSeed("hard", bad));
}
assert.throws(() => ns.validateTierAndSeed("hard_forge", 3000));

const fixtures = JSON.parse(process.env.FIXTURES_JSON);
const writtenFiles = {};
const mockPyodide = {
  FS: {
    mkdirTree() {},
    writeFile(p, content) { writtenFiles[p] = content; },
  },
  runPython(code) {
    if (code.includes("start_solver_session")) return null;
    if (code.includes("get_solver_day_state_json(3, False")) return fixtures.d3_locked;
    if (code.includes("get_solver_day_state_json(9, False")) return fixtures.d9_locked;
    if (code.includes("get_solver_day_state_json(9, True")) return fixtures.d9_unlocked;
    return true;
  },
};

await ns.initSolverLive(mockPyodide, { pythonSource: "def placeholder(): pass" });
assert.ok(Object.keys(writtenFiles).some((k) => k.endsWith("solver_live.py")));

const session = ns.createSession(mockPyodide, "hard", 26);
const d3 = session.getSolverDayState(3, false);
assert.equal(d3.status, "hunting");
assert.equal(d3.sealed_day, null);
assert.equal("accused" in d3, false);
assert.equal(session.formatAccusedTarget(3, false), "[SEALED]");

const d9Locked = session.getSolverDayState(9, false);
assert.equal(d9Locked.status, "sealed_accusation");
assert.equal(d9Locked.sealed_day, 7);
assert.equal("accused" in d9Locked, false);
assert.equal(session.formatAccusedTarget(9, false), "[SEALED]");

const d9TruthyNonBool = session.getSolverDayState(9, 1);
assert.equal(d9TruthyNonBool.status, "sealed_accusation");
assert.equal("accused" in d9TruthyNonBool, false);

const d9Revealed = session.getSolverDayState(9, true);
assert.equal(d9Revealed.status, "revealed");
assert.equal(d9Revealed.accused, "e08");
assert.equal(d9Revealed.final_day, 7);
assert.ok(Math.abs(d9Revealed.score - 0.69) < 1e-12);
assert.equal(session.formatAccusedTarget(9, true), "e08");

assert.throws(() => ns.sanitizeSolverState({ ...d9Locked, visible_V: "e08" }, false));
"""

    env = dict(os.environ)
    env["JS_MOD_PATH"] = str(JS_MOD_PATH)
    env["FIXTURES_JSON"] = json.dumps(fixtures)
    res = subprocess.run(
        ["node", "--input-type=module", "-e", node_script],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0, f"node failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
