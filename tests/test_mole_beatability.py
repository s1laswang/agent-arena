from __future__ import annotations

import ast
import json
from pathlib import Path

import numpy as np
import pytest

from canary.env import Env
from canary.eval import run_episode
from canary.forge.frontier_proxies import GeminiCarbonProxy
from canary.forge.rl_mole import RLMole, default_like_params
from canary.mole.beatability import (
    DEFAULT_MIN_SOLVER_ACC,
    DROP_REASONS,
    GATE_NAMES,
    PublicToolFirewall,
    audit_beatability,
    audit_hof_beatability,
    check_anti_side_channel,
    filter_candidates,
    luck_adjusted_episode_score,
    main,
    summarize_candidates,
)
from canary.mole.counterfactual import BUILTIN_CANDIDATES
from canary.mole.dsl import DEFAULT_STRATEGY, MoleStrategy
from canary.solver.policy import SolverPolicy
from canary.types import EpisodeResult, Step

ROOT = Path(__file__).resolve().parents[1]
HOF_V13 = ROOT / "data" / "forge" / "hall_of_fame_v1.3.jsonl"


def test_hygiene_and_zero_social_imports():
    hash_ch = chr(35)
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    forbidden_ref = "solver_" + "v2"
    for rel in ("canary/mole/beatability.py", "tests/test_mole_beatability.py"):
        txt = (ROOT / rel).read_text(encoding="utf-8")
        assert hash_ch not in txt, rel
        assert em_dash not in txt, rel
        assert en_dash not in txt, rel
        assert forbidden_ref not in txt, rel

    tree = ast.parse((ROOT / "canary/mole/beatability.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert "social" not in node.module
        elif isinstance(node, ast.Import):
            for alias in node.names:
                assert "social" not in alias.name


def test_public_tool_firewall_blocks_private_state_and_preserves_solver():
    raw_a = Env("medium", 6003)
    raw_b = Env("medium", 6003)
    fw = PublicToolFirewall(raw_b)

    for hidden_attr in ("_world", "_mole", "_held", "_leaked", "_ledger", "ledger", "verdict"):
        with pytest.raises(AttributeError):
            getattr(fw, hidden_attr)

    res_raw = run_episode(raw_a, SolverPolicy("medium"))
    res_fw = run_episode(fw, SolverPolicy("medium"))
    assert [(s.tool, s.args) for s in res_raw.steps] == [(s.tool, s.args) for s in res_fw.steps]
    assert res_raw.accused == res_fw.accused
    assert res_raw.score == res_fw.score
    assert res_raw.correct == res_fw.correct

    la_score, p_acc = luck_adjusted_episode_score(res_fw)
    assert p_acc is not None and 0.6 <= p_acc <= 1.0
    assert -1.0 <= la_score <= 1.0


def test_default_and_framed_strategies_pass_beatability_and_paired_regret():
    assert DEFAULT_MIN_SOLVER_ACC == pytest.approx(0.85)
    seeds = [6222]

    def_rep = audit_beatability(
        DEFAULT_STRATEGY, tier="hard", seeds=seeds, include_codex_proxy=True, probe_count=1
    )
    assert tuple(def_rep["gates"].keys()) == GATE_NAMES
    assert def_rep["verdict"] == "kept"
    assert def_rep["reason"] == ""
    assert def_rep["beatable"] is True
    assert def_rep["all_passed"] is True
    assert def_rep["solver_acc"] >= 0.85
    assert def_rep["proxy_name"] == GeminiCarbonProxy.name
    assert def_rep["proxy_fails"] > 0
    assert def_rep["paired_regret"] > 0.0
    assert def_rep["luck_adjusted_regret"] > 0.0
    assert "codex_paired_regret" in def_rep["gates"]["paired_regret"]
    assert len(def_rep["per_seed"]) == len(seeds)

    framed_rep = audit_beatability(
        BUILTIN_CANDIDATES["frame_decoy_seeded"], tier="hard", seeds=seeds, probe_count=1
    )
    assert framed_rep["verdict"] == "kept"
    assert framed_rep["solver_acc"] >= 0.85
    assert framed_rep["paired_regret"] > def_rep["paired_regret"]
    assert framed_rep["paired_regret_gain"] > 0.0


def test_hof_v13_passes_strict_085_beatability():
    rep = audit_hof_beatability(HOF_V13, tier="hard", seeds=[6222])
    assert rep["n_strategies"] == 1
    assert rep["n_kept"] == 1
    assert rep["n_beatable"] == 1
    assert rep["all_passed"] is True
    strat = rep["strategies"][0]
    assert strat["solver_acc"] >= 0.85
    assert strat["proxy_fails"] > 0
    assert strat["paired_regret"] > 0.0
    assert rep["summary"]["kept"] == 1
    assert rep["summary"]["dropped"] == 0


def test_unbeatable_and_canary_starving_moles_dropped():
    never_leak = {"rules": [], "default": {"leak": "none", "frame": "decoy"}}
    r_never = audit_beatability(never_leak, tier="medium", seeds=[6003], probe_count=1)
    assert r_never["gates"]["valid_strategy"]["passed"] is True
    assert r_never["gates"]["anti_side_channel"]["passed"] is True
    assert r_never["gates"]["blind_diligence"]["passed"] is True
    assert r_never["gates"]["solver_beatable"]["passed"] is False
    assert r_never["solver_acc"] < 0.85
    assert r_never["verdict"] == "dropped"
    assert r_never["reason"] == "unbeatable"
    assert r_never["beatable"] is False

    shy = BUILTIN_CANDIDATES["canary_shy_frame_decoy"]
    r_shy = audit_beatability(shy, tier="medium", seeds=[6003], probe_count=1)
    assert r_shy["solver_acc"] < 0.85
    assert r_shy["verdict"] == "dropped"
    assert r_shy["reason"] == "unbeatable"

    r_sr = audit_beatability(DEFAULT_STRATEGY, tier="medium", seeds=[6003], include_step_regret=True, probe_count=1)
    assert r_sr["gates"]["paired_regret"]["proxy_mean_step_regret"] >= 0.0


def test_blind_diligence_and_side_channel_probes():
    easy_rep = audit_beatability(DEFAULT_STRATEGY, tier="easy", seeds=[6000], probe_count=1)
    assert easy_rep["gates"]["blind_diligence"]["passed"] is False
    assert easy_rep["verdict"] == "dropped"
    assert easy_rep["reason"] == "blind_diligence_wins"

    leaky_step = Step(
        t=0,
        day=1,
        tool="status",
        args={},
        result={"ok": True, "data": {"hint": "strategy_json leaked"}, "error": None},
    )
    leaky_ep = EpisodeResult(
        tier="hard",
        seed=6000,
        agent="solver",
        steps=[leaky_step],
        score=0.5,
        accused="e00",
        correct=True,
        final_day=1,
        end_reason="accused",
        meta={"V": 0.5},
    )
    sc_gate = check_anti_side_channel(
        DEFAULT_STRATEGY,
        tier="medium",
        seeds=[6003],
        solver_episodes=[leaky_ep],
        probe_count=1,
    )
    assert sc_gate["passed"] is False
    assert any("strategy_json" in v for v in sc_gate["violations"])


def test_sleeper_ported_candidate_filter_and_drop_reasons():
    table = {
        "good_a": {"name": "good_a", "solver_acc": 0.90, "solver_score": 0.55, "proxy_acc": 0.70, "proxy_fails": 6, "proxy_score": 0.25, "paired_regret": 0.30},
        "bad_dsl": {"name": "bad_dsl", "valid_strategy": False},
        "bad_sc": {"name": "bad_sc", "anti_side_channel": False, "solver_acc": 0.95, "proxy_fails": 5, "paired_regret": 0.25},
        "bad_blind": {"name": "bad_blind", "blind_diligence": False, "solver_acc": 0.95, "proxy_fails": 5, "paired_regret": 0.25},
        "bad_unbeatable": {"name": "bad_unbeatable", "solver_acc": 0.75, "proxy_fails": 8, "paired_regret": 0.35},
        "bad_nogap": {"name": "bad_nogap", "solver_acc": 0.95, "proxy_fails": 0, "paired_regret": 0.10},
        "bad_regret": {"name": "bad_regret", "solver_acc": 0.90, "proxy_fails": 3, "paired_regret": -0.05},
    }

    def stub_runner(cand_key: str, _seeds: list[int]) -> dict:
        return dict(table[cand_key])

    kept, dropped = filter_candidates(list(table.keys()), seeds=[1, 2, 3], runner=stub_runner)
    assert [k["strategy_name"] for k in kept] == ["good_a"]
    got_reasons = {reason for _, reason in dropped}
    assert got_reasons == set(DROP_REASONS)

    summ = summarize_candidates(kept, dropped)
    assert summ["kept"] == 1
    assert summ["dropped"] == 6
    assert summ["mean_paired_regret"] == pytest.approx(0.30)
    assert summ["mean_solver_acc"] == pytest.approx(0.90)


def test_invalid_inputs_rl_mole_and_cli(tmp_path, capsys):
    for bad in (
        None,
        "invalid",
        {"default": {"leak": "unknown_selector", "frame": "none"}},
        MoleStrategy(rules=(((), ("newest", "none")),) * 13),
    ):
        rep = audit_beatability(bad, tier="hard", seeds=[6222])
        assert rep["verdict"] == "dropped"
        assert rep["reason"] == "invalid_strategy"
        assert rep["all_passed"] is False

    params = default_like_params(seed=0)
    rl_ok = audit_beatability(
        RLMole(params, name="rl_ok").to_json(), tier="medium", seeds=[6003], probe_count=1
    )
    assert rl_ok["strategy_kind"] == "rl_mole"
    assert rl_ok["gates"]["valid_strategy"]["passed"] is True
    assert rl_ok["gates"]["anti_side_channel"]["passed"] is True

    bad_params = {k: v.copy() for k, v in params.items()}
    bad_params["W1"][0, 0] = np.nan
    rl_bad = audit_beatability(RLMole(bad_params, name="rl_nan").to_json(), tier="hard", seeds=[6222])
    assert rl_bad["verdict"] == "dropped"
    assert rl_bad["reason"] == "invalid_strategy"

    out_file = tmp_path / "beatability_hof.json"
    rc = main(["--hof", str(HOF_V13), "--tier", "hard", "--seeds", "6222", "--out", str(out_file)])
    out_stdout = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out_stdout["all_passed"] is True
    assert json.loads(out_file.read_text(encoding="utf-8")) == out_stdout
