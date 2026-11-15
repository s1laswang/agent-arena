from __future__ import annotations

import copy
import importlib.util
import io
import json
import math
import subprocess
import tokenize
from pathlib import Path

import pytest

from canary import rules
from canary.env import Env
from canary.rules import DEV_SEEDS, HELDOUT_SEEDS, JUDGE_SEEDS, TIERS_VERSION

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "export_arena_duel_pack.py"
PACK_JS_PATH = ROOT / "docs" / "arena" / "data" / "committed_duel_pack.js"
SELF_PATH = Path(__file__).resolve()


def _load_export_mod():
    spec = importlib.util.spec_from_file_location("export_arena_duel_pack_local", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


mod = _load_export_mod()

HASH_CH = chr(35)
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
UNICODE_MINUS = chr(0x2212)
SLASH_SLASH = chr(47) * 2
SLASH_STAR = chr(47) + chr(42)
STAR_SLASH = chr(42) + chr(47)


def test_duel_pack_files_strict_hygiene() -> None:
    for path in (SCRIPT_PATH, PACK_JS_PATH, SELF_PATH):
        assert path.is_file(), f"missing {path}"
        raw = path.read_text(encoding="utf-8")
        assert len(raw.strip()) > 0
        assert raw.isascii(), f"non-ASCII character in {path}"
        assert EM_DASH not in raw
        assert EN_DASH not in raw
        assert UNICODE_MINUS not in raw
        assert HASH_CH not in raw
        assert SLASH_SLASH not in raw
        assert SLASH_STAR not in raw
        assert STAR_SLASH not in raw
        assert "Co-Authored-" + "By" not in raw
        if path.suffix == ".js":
            for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
                assert sink not in raw
        if path.suffix == ".py":
            tokens = list(tokenize.generate_tokens(io.StringIO(raw).readline))
            comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
            assert comments == []


def test_export_arena_duel_pack_deterministic_sync_and_seed_firewall() -> None:
    assert TIERS_VERSION == "v1.4"
    assert rules.KNOWN_V_MODE is True

    for seed in (*mod.HARD_SEEDS, *mod.MEDIUM_SEEDS):
        assert seed in DEV_SEEDS
        assert seed not in JUDGE_SEEDS
        assert seed not in HELDOUT_SEEDS
        mod._validate_dev_seed(seed)

    for forbidden_seed in (next(iter(JUDGE_SEEDS)), next(iter(HELDOUT_SEEDS)), -1, 999999):
        with pytest.raises(ValueError):
            mod._validate_dev_seed(forbidden_seed)

    pack = mod.build_duel_pack_dict()
    rendered = mod.render_duel_pack_js(pack)
    assert PACK_JS_PATH.read_text(encoding="utf-8") == rendered

    stats = mod.run_self_check(PACK_JS_PATH)
    assert stats["worlds"] == 10
    assert stats["paired_episodes"] == 20
    assert math.isclose(stats["seed6_gemini"], 0.73, abs_tol=1e-9)
    assert math.isclose(stats["seed6_solver"], 0.71, abs_tol=1e-9)
    assert math.isclose(stats["seed26_gemini"], -1.0, abs_tol=1e-9)
    assert math.isclose(stats["seed26_solver"], 0.69, abs_tol=1e-9)


def test_duel_pack_env_replay_parity_and_known_v_isolation() -> None:
    pack = mod.build_duel_pack_dict()
    assert pack["schema_version"] == "canary_duel_pack.v1"
    assert pack["seeds_by_tier"] == {
        "hard": [6, 26, 4, 18, 15, 11, 5, 23],
        "medium": [0, 12],
    }

    unsurfaced_gap_steps = 0
    total_steps = 0

    for tier, seeds in (("hard", mod.HARD_SEEDS), ("medium", mod.MEDIUM_SEEDS)):
        for seed in seeds:
            world_key = f"{tier}:{seed}"
            assert world_key in pack["worlds"]
            for agent_id in ("gemini", "solver"):
                ep_key = f"{world_key}:{agent_id}"
                ep = pack["episodes"][ep_key]
                env = Env(tier, seed)
                raw_map = mod._load_committed_seed_map(mod.COMMITTED_V14_ROOT, mod.RUN_PATHS[(tier, agent_id)])
                _, raw_ep = raw_map[seed]
                raw_steps = raw_ep["steps"]
                assert len(ep["steps"]) == len(raw_steps)

                for idx, (pub_st, raw_st) in enumerate(zip(ep["steps"], raw_steps)):
                    live_res = env.call(raw_st["tool"], raw_st["args"])
                    known_v = env.visible_V()
                    true_v = round(env.V, 10)
                    total_steps += 1
                    if abs(known_v - true_v) > 1e-9:
                        unsurfaced_gap_steps += 1
                    assert pub_st["day"] == int(raw_st["day"])
                    assert pub_st["call_idx"] == idx
                    assert pub_st["t"] == idx
                    assert pub_st["tool"] == raw_st["tool"]
                    assert pub_st["ok"] is bool(live_res.ok)
                    assert math.isclose(float(pub_st["V"]), known_v, abs_tol=1e-9)
                    assert math.isclose(float(pub_st["known_v"]), known_v, abs_tol=1e-9)

                verdict = env.verdict()
                rev = mod.unseal_reveal_token(ep)
                assert math.isclose(float(rev["score"]), float(verdict["score"]), abs_tol=1e-9)
                assert rev["correct"] is bool(verdict["correct"])
                assert rev["accused"] == verdict["accused"]
                assert rev["mole"] == env._world.mole
                assert rev["decoy"] == env._world.decoy
                assert rev["final_day"] == int(verdict["final_day"])
                assert rev["end_reason"] == verdict["end_reason"]
                assert rev["tool_calls"] == len(raw_steps)

    assert total_steps > 1500
    assert unsurfaced_gap_steps > 200

    s4_gem = mod.unseal_reveal_token(pack["episodes"]["hard:4:gemini"])
    s4_sol = mod.unseal_reveal_token(pack["episodes"]["hard:4:solver"])
    assert math.isclose(s4_gem["score"], 0.40, abs_tol=1e-9)
    assert math.isclose(s4_sol["score"], 0.73, abs_tol=1e-9)
    assert s4_gem["mole"] == "e11"

    s11_gem = mod.unseal_reveal_token(pack["episodes"]["hard:11:gemini"])
    s11_sol = mod.unseal_reveal_token(pack["episodes"]["hard:11:solver"])
    assert math.isclose(s11_gem["score"], 0.0, abs_tol=1e-9)
    assert s11_gem["accused"] is None
    assert s11_gem["end_reason"] == "horizon"
    assert math.isclose(s11_sol["score"], 0.62, abs_tol=1e-9)
    assert s11_gem["mole"] == "e09"


def test_duel_pack_pre_end_zero_leak_and_negative_controls() -> None:
    pack = mod.build_duel_pack_dict()
    mod._assert_zero_pre_end_leaks(pack)

    accuse_count = 0
    for ep in pack["episodes"].values():
        for st in ep["steps"]:
            if st["tool"] == "accuse":
                accuse_count += 1
                assert st["sealed"] is True
                assert st["args"] == {"employee": "[SEALED]"}
                assert st["target_employee"] == "[SEALED]"
                assert "[SEALED]" in st["summary"]

    assert accuse_count == 19

    leaked_mole = copy.deepcopy(pack)
    leaked_mole["episodes"]["hard:6:gemini"]["mole"] = "e34"
    with pytest.raises(AssertionError, match="mole"):
        mod._assert_zero_pre_end_leaks(leaked_mole)

    leaked_score = copy.deepcopy(pack)
    leaked_score["episodes"]["hard:26:gemini"]["score"] = -1.0
    with pytest.raises(AssertionError, match="score"):
        mod._assert_zero_pre_end_leaks(leaked_score)

    leaked_accuse = copy.deepcopy(pack)
    leaked_accuse["episodes"]["hard:26:gemini"]["steps"][-1]["args"]["employee"] = "e04"
    with pytest.raises(AssertionError, match="unsealed accuse args"):
        mod._assert_zero_pre_end_leaks(leaked_accuse)


def test_duel_pack_node_runtime_cjs_and_window_helpers() -> None:
    node_bin = mod._find_node_bin()
    assert node_bin is not None

    script = (
        "const pack = require(process.argv[1]);"
        "const assert = require('node:assert/strict');"
        "assert.equal(globalThis.CANARY_DUEL_PACK, pack);"
        "assert.equal(globalThis.CANARY_GEMINI_REPLAYS, pack);"
        "assert.deepEqual(pack.listSeeds('hard'), [6, 26, 4, 18, 15, 11, 5, 23]);"
        "assert.deepEqual(pack.listSeeds('medium'), [0, 12]);"
        "assert.equal(pack.episodes['hard:26'], pack.episodes['hard:26:gemini']);"
        "assert.equal(pack.episodes['26'], pack.episodes['hard:26:gemini']);"
        "assert.equal(pack.by_agent['hard:26:solver'], pack.episodes['hard:26:solver']);"
        "for (let d = 1; d <= 5; d++) {"
        "  const preEarly = pack.getPreEndEpisode('hard', 6, d);"
        "  assert.equal(preEarly.status, 'in_progress');"
        "  assert.equal(preEarly.final, null);"
        "  assert.equal(preEarly.steps.every((s) => s.day <= d), true);"
        "}"
        "const pre6 = pack.getPreEndEpisode('hard', 6, 6);"
        "assert.equal(pre6.status, 'sealed_accusation');"
        "assert.equal(pre6.sealed_day, 6);"
        "assert.deepEqual(pre6.final, { sealed: true, final_day: 6 });"
        "const last6 = pre6.steps[pre6.steps.length - 1];"
        "assert.equal(last6.tool, 'accuse');"
        "assert.equal(last6.args.employee, '[SEALED]');"
        "assert.equal(last6.sealed, true);"
        "const pre11 = pack.getPreEndEpisode('hard', 11, 21);"
        "assert.equal(pre11.status, 'horizon_ended');"
        "assert.deepEqual(pre11.final, { sealed: true, final_day: 21 });"
        "const preSol26 = pack.getPreEndEpisode('hard', 26, 'solver');"
        "assert.equal(preSol26.agent_id, 'solver');"
        "assert.equal(preSol26.steps.length, 60);"
        "assert.equal(pack.unlockPostGameReveal('hard', 26, false), null);"
        "assert.equal(pack.unlockPostGameReveal(26, false), null);"
        "assert.equal(pack.getUnlockedEpisode('hard', 6, false), null);"
        "const rev26 = pack.unlockPostGameReveal('hard', 26, true);"
        "assert.equal(rev26.mole, 'e08');"
        "assert.equal(rev26.accused, 'e04');"
        "assert.equal(rev26.score, -1.0);"
        "assert.equal(rev26.solver.score, 0.69);"
        "const rev26Sol = pack.unlockPostGameReveal('hard', 26, true, 'solver');"
        "assert.equal(rev26Sol.accused, 'e08');"
        "assert.equal(rev26Sol.score, 0.69);"
        "const unl6 = pack.getUnlockedEpisode('hard', 6, true, 'gemini');"
        "assert.equal(unl6.steps[unl6.steps.length - 1].args.employee, 'e34');"
        "assert.equal(unl6.steps[unl6.steps.length - 1].sealed, false);"
        "assert.equal(unl6.final.score, 0.73);"
    )
    proc = subprocess.run(
        [node_bin, "-e", script, str(PACK_JS_PATH)],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 0, proc.stderr


def test_duel_pack_cli_check_mode() -> None:
    assert mod.main(["--check", "--out", str(PACK_JS_PATH)]) == 0
