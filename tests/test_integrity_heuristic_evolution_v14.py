from __future__ import annotations

import copy
import importlib.util
import io
import json
import random
import sys
import tokenize
from pathlib import Path

import pytest

from canary.eval import make_env, run_episode
from canary.redteam.swarm_probes import W2b008Elimination

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "integrity_heuristic_evolution_v14.py"
REPORT_PATH = ROOT / "docs" / "reports" / "integrity_heuristic_evolution_v14.md"


def _load_module():
    spec = importlib.util.spec_from_file_location("integrity_heuristic_evolution_v14", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


evo_mod = _load_module()


@pytest.fixture(scope="module")
def quick_cli_run(tmp_path_factory):
    out_dir = tmp_path_factory.mktemp("evo_v14_quick")
    out_json = out_dir / "quick_out.json"
    rc = evo_mod.main(["--quick", "--workers", "1", "--json-out", str(out_json)])
    raw = out_json.read_text(encoding="utf-8")
    parsed = json.loads(
        raw,
        parse_constant=lambda c: (_ for _ in ()).throw(ValueError(f"non-standard JSON constant {c}")),
    )
    return rc, parsed


def test_quick_cli_end_to_end_and_schema(quick_cli_run):
    rc, rep = quick_cli_run
    assert rc == 0
    assert rep["mode"] == "quick"
    assert rep["workers"] == 1
    assert rep["live_llm_calls"] == 0
    assert rep["passed_all_integrity_gates"] is True
    assert rep["total_tool_calls"] > 500

    pa = rep["part_a_evolution"]
    assert pa["search_stats"]["distinct_policies_evaluated"] >= 3
    assert "swarm_w2b008" in pa["dev_oos"]["policies"]
    assert "swarm_w2b008" in pa["judge_public"]["policies"]
    for split_key in ("dev_oos", "judge_public"):
        assert set(pa[split_key]["solver"]) == set(evo_mod.ALL_TARGETS)
        for pdata in pa[split_key]["policies"].values():
            assert set(pdata["tiers"]) == set(evo_mod.ALL_TARGETS)

    for eb_key in ("part_b_effort_ladder_dev_oos", "part_b_effort_ladder_judge_oos"):
        eb = rep[eb_key]
        assert eb["all_stop_without_accusing_exact_zero"] is True
        assert set(eb["targets"]) == {"hard_forge", "hard_rl"}
        for tdata in eb["targets"].values():
            assert tdata["solver_minus_accuse_nonzero_count"] == 0
            assert set(tdata["cuts"]) == {"10%", "25%", "50%", "75%", "90%"}
            for crow in tdata["cuts"].values():
                assert crow["stop_without_accusing_nonzero_count"] == 0
                assert crow["stop_without_accusing_max_abs"] == 0.0

    hc = rep["part_c_pythonhashseed"]
    assert hc["bit_identical"] is True
    assert hc["mismatches"] == []
    assert hc["distinct_builtin_str_hashes"] == 2
    assert "easy:30201" in hc["reference_cells"]
    assert len(hc["reference_cells"]["easy:30201"]["tool_outputs_sha256"]) == 64

    ac = rep["part_c_seed_autocorrelation"]
    assert ac["zero_sequential_predictability"] is True
    bf = ac["boundary_forensics"]
    assert bf["mcp_server_allowed_900000_900039"] == 40
    assert bf["mcp_server_allowed_900040_900199"] == 0
    assert bf["keyed_helper_exact_match_on_900000_900039"] == 40


def test_w2b008_parity_and_evolved_policy_variants():
    for tier, seed in (("easy", 30201), ("hard", 30201)):
        env_ref = make_env(tier, seed)
        res_ref = run_episode(env_ref, W2b008Elimination(seed=seed))
        env_par = make_env(tier, seed)
        res_par = run_episode(env_par, evo_mod.ParameterizedEliminationPolicy(evo_mod.W2B008_CONFIG, seed=seed))
        assert res_par.score == pytest.approx(res_ref.score, abs=1e-9)
        assert res_par.accused == res_ref.accused
        assert len(res_par.steps) == len(res_ref.steps)

    cfg_variant = evo_mod.HeuristicConfig(
        first_canary_size=10,
        followup_canary_size=4,
        variant_partitions=3,
        decoy_rule="anger_majority",
        after_hours_weight=1.0,
        interview_budget=2,
        min_pool_to_accuse=2,
        accuse_day_threshold=14,
        elimination_mode="weighted_strikes",
        second_canary_mode="orthogonal",
    )
    env_v = make_env("medium", 30201)
    res_v = run_episode(env_v, evo_mod.ParameterizedEliminationPolicy(cfg_variant, seed=30201))
    assert -1.0 <= res_v.score <= 1.0

    grid = evo_mod.build_structured_grid(12, seed=99)
    assert len(grid) == 12
    assert len(set(grid)) == 12
    assert grid[0] == evo_mod.W2B008_CONFIG

    rng = random.Random(123)
    mutated = evo_mod.mutate_config(evo_mod.W2B008_CONFIG, rng, n_genes=2)
    diff_genes = [k for k in mutated.to_dict() if mutated.to_dict()[k] != evo_mod.W2B008_CONFIG.to_dict()[k]]
    assert len(diff_genes) == 2
    crossed = evo_mod.crossover_configs(evo_mod.W2B008_CONFIG, cfg_variant, rng)
    for k, val in crossed.to_dict().items():
        assert val in (evo_mod.W2B008_CONFIG.to_dict()[k], cfg_variant.to_dict()[k])


def test_statistical_and_effort_ladder_detectors_fail_closed(quick_cli_run):
    assert evo_mod.chi2_sf(3.8414588, 1) == pytest.approx(0.05, abs=5e-4)
    assert evo_mod.chi2_sf(0.0, 9) == 1.0

    tie_stats = evo_mod.paired_bootstrap_stats([0.5, 0.4, 0.0], [0.5, 0.4, 0.0], n_boot=500, boot_seed=7)
    assert tie_stats["paired_mean_diff"] == 0.0
    assert tie_stats["significantly_above_solver"] is False
    assert tie_stats["ties"] == 3

    win_stats = evo_mod.paired_bootstrap_stats([0.8] * 20, [0.2] * 20, n_boot=500, boot_seed=7)
    assert win_stats["beats_solver_in_mean"] is True
    assert win_stats["significantly_above_solver"] is True

    planted_cycle = [[i % 40 for i in range(200)]]
    cyc_metrics = evo_mod.sequence_chisq_metrics(planted_cycle, n_states=40, lags=(1, 2), mc_trials=100, mc_seed=11)
    assert cyc_metrics["lags"]["lag_1"]["bucket4x4_p"] < 1e-6
    assert cyc_metrics["lags"]["lag_1"]["dept_mod5x5_p"] < 1e-6
    assert cyc_metrics["lags"]["lag_1"]["full40x40_mc_p"] < 0.02

    fake_cache = {
        "hard_forge": {
            1: {
                "score": 0.4,
                "correct": True,
                "n_calls": 50,
                "effort": {
                    "minus_accuse_score": 0.0,
                    "stop_scores": {p: (0.25 if p == 50 else 0.0) for p in evo_mod.EFFORT_CUTS},
                    "guess_scores": {p: (0.8 if p == 90 else -1.0) for p in evo_mod.EFFORT_CUTS},
                    "guess_post_ingest_scores": {p: (0.8 if p == 90 else -1.0) for p in evo_mod.EFFORT_CUTS},
                    "guess_correct": {p: (p == 90) for p in evo_mod.EFFORT_CUTS},
                    "guess_days": {p: 5 for p in evo_mod.EFFORT_CUTS},
                },
            }
        },
        "hard_rl": {},
    }
    fake_cache["hard_rl"][1] = copy.deepcopy(fake_cache["hard_forge"][1])
    fake_cache["hard_rl"][1]["effort"]["stop_scores"][50] = 0.0
    fake_cache["hard_rl"][1]["effort"]["guess_scores"][90] = -0.2
    fake_cache["hard_rl"][1]["effort"]["guess_post_ingest_scores"][90] = -0.2
    bad_summary = evo_mod.summarize_effort_ladder(fake_cache, [1], n_boot=200)
    assert bad_summary["all_stop_without_accusing_exact_zero"] is False
    assert bad_summary["all_early_argmax_strictly_below_solver"] is False


def test_report_metrics_and_strict_hygiene():
    assert REPORT_PATH.is_file()
    txt = REPORT_PATH.read_text(encoding="utf-8")
    assert len(txt.encode("utf-8")) <= 130 * 1024

    for required in (
        "1,040",
        "18,800",
        "30200-30399",
        "900000-900039",
        "0.5768",
        "0.4505",
        "0.3261",
        "0.5099",
        "0.4946",
        "post-hoc lock",
        "65% [24%, 98%]",
        "PYTHONHASHSEED",
    ):
        assert required in txt, required

    lower_txt = txt.lower()
    assert "pre-reg" not in lower_txt
    assert "prereg" not in lower_txt
    for bad_dash in ("\u2014", "\u2013", "\u2212"):
        assert bad_dash not in txt

    for py_path in (SCRIPT_PATH, Path(__file__).resolve()):
        src = py_path.read_text(encoding="utf-8")
        for bad_dash in ("\u2014", "\u2013", "\u2212"):
            assert bad_dash not in src, py_path
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
        comments = [t for t in toks if t.type == tokenize.COMMENT]
        assert comments == [], (py_path, comments)
