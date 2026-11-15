from __future__ import annotations

import json
from pathlib import Path

import pytest

from canary.env import Env
from canary.eval import run_episode
from canary.forge.proxy_ensemble import (
    CodexGPT55Proxy,
    FRONTIER_PROXY_NAMES,
    GeminiCarbonInProcProxy,
    GeminiCarbonOpenCodeProxy,
    MultiModelProxySuite,
    TRANSCRIPT_ENSEMBLE_STRATEGY,
    evaluate_proxy_ensemble,
    frontier_ensemble_investigators,
    main,
    search_ensemble_strategies,
)
from canary.mole.dsl import DEFAULT_STRATEGY, MoleStrategy
from canary.types import INVESTIGATIVE_TOOLS

ROOT = Path(__file__).resolve().parent.parent


def _episode_profile(ep):
    inv_steps = [s for s in ep.steps if s.tool in INVESTIGATIVE_TOOLS and (s.result or {}).get("ok")]
    iv_steps = [s for s in inv_steps if s.tool == "interview"]
    canary_steps = [s for s in inv_steps if s.tool == "plant_canary"]
    rec_sizes = [len(s.args["assignment"]) for s in canary_steps]
    var_counts = [len(set(s.args["assignment"].values())) for s in canary_steps]
    first_canary_day = canary_steps[0].day if canary_steps else None
    le3_share = sum(1 for n in rec_sizes if n <= 3) / len(rec_sizes) if rec_sizes else 0.0
    iv_share = len(iv_steps) / len(inv_steps) if inv_steps else 0.0
    trace = [(s.day, s.tool, s.args) for s in ep.steps]
    return {
        "iv_count": len(iv_steps),
        "iv_share": iv_share,
        "first_canary_day": first_canary_day,
        "rec_sizes": rec_sizes,
        "var_counts": var_counts,
        "le3_share": le3_share,
        "trace": trace,
    }


def test_suite_and_factory_exports():
    proxies_only = frontier_ensemble_investigators(include_baselines=False)
    assert set(proxies_only.keys()) == set(FRONTIER_PROXY_NAMES)

    with_baselines = frontier_ensemble_investigators(include_baselines=True)
    assert set(FRONTIER_PROXY_NAMES).issubset(with_baselines.keys())
    assert {"heuristic", "hinted_heuristic", "grok_tactics"}.issubset(with_baselines.keys())

    suite = MultiModelProxySuite()
    assert isinstance(suite, dict)
    assert set(suite.keys()) == set(with_baselines.keys())
    assert suite.proxy_names == FRONTIER_PROXY_NAMES
    assert set(suite.frontier_factories().keys()) == set(FRONTIER_PROXY_NAMES)

    for name, factory in suite.items():
        inst = factory(6400)
        assert hasattr(inst, "reset") and hasattr(inst, "act"), name


def test_behavioral_differentiation_and_determinism_hard_6400():
    runs = {}
    for cls in (GeminiCarbonOpenCodeProxy, GeminiCarbonInProcProxy, CodexGPT55Proxy):
        ep_a = run_episode(Env("hard", 6400), cls(seed=6400))
        ep_b = run_episode(Env("hard", 6400), cls(seed=6400))
        assert ep_a.end_reason in ("accused", "horizon")
        assert ep_a.meta.get("valid") is not False
        assert ep_a.score == ep_b.score
        assert ep_a.accused == ep_b.accused
        assert ep_a.final_day == ep_b.final_day
        prof_a = _episode_profile(ep_a)
        prof_b = _episode_profile(ep_b)
        assert prof_a["trace"] == prof_b["trace"]
        runs[cls.name] = prof_a

    oc = runs["gemini_opencode_proxy"]
    ip = runs["gemini_inproc_proxy"]
    cx = runs["codex_gpt55_proxy"]

    assert cx["first_canary_day"] == 1
    assert cx["le3_share"] >= 0.30
    assert any(n <= 3 for n in cx["rec_sizes"])
    assert all(v == 2 for v in cx["var_counts"])

    assert oc["first_canary_day"] is not None and oc["first_canary_day"] >= 2
    assert ip["first_canary_day"] is not None and ip["first_canary_day"] >= 2
    assert all(n >= 4 for n in oc["rec_sizes"])
    assert all(n >= 4 for n in ip["rec_sizes"])
    assert all(v == 3 for v in oc["var_counts"])
    assert all(v == 3 for v in ip["var_counts"])

    assert oc["iv_count"] > cx["iv_count"]
    assert ip["iv_count"] > cx["iv_count"]
    assert oc["iv_count"] >= ip["iv_count"]
    assert oc["iv_share"] > 0.55
    assert ip["iv_share"] > 0.55
    assert cx["iv_share"] < 0.25

    cx_med = _episode_profile(run_episode(Env("medium", 6400), CodexGPT55Proxy(seed=6400)))
    assert cx_med["first_canary_day"] == 1
    assert cx_med["le3_share"] >= 0.50
    assert 3 in cx_med["var_counts"]


def test_seed_hygiene_rejection():
    for bad_seed in (0, 29, 800_000, 900_000, -1):
        with pytest.raises(ValueError):
            evaluate_proxy_ensemble(DEFAULT_STRATEGY, tier="hard", seeds=[bad_seed])

    with pytest.raises(ValueError):
        evaluate_proxy_ensemble(DEFAULT_STRATEGY, tier="hard", seeds=[])

    with pytest.raises(ValueError):
        search_ensemble_strategies(
            n_mutations=2,
            train_seeds=[0, 31],
            holdout_seeds=[6420, 6421],
        )

    with pytest.raises(ValueError):
        search_ensemble_strategies(
            n_mutations=2,
            train_seeds=[6400, 6401],
            holdout_seeds=[800_000, 800_001],
        )

    with pytest.raises(ValueError):
        search_ensemble_strategies(
            n_mutations=2,
            train_seeds=[6400, 6401],
            holdout_seeds=[6401, 6402],
        )


def test_evaluate_proxy_ensemble_six_seeds_schema_and_dominance():
    seeds = range(6400, 6406)
    def_res = evaluate_proxy_ensemble(DEFAULT_STRATEGY, tier="hard", seeds=seeds)
    ens_res = evaluate_proxy_ensemble(TRANSCRIPT_ENSEMBLE_STRATEGY, tier="hard", seeds=seeds)

    for res in (def_res, ens_res):
        assert res["n_seeds"] == 6
        assert res["seeds"] == list(seeds)
        assert isinstance(res["feasible"], bool)
        assert isinstance(res["pareto_dominates_default"], bool)
        assert set(res["per_proxy"].keys()) == set(FRONTIER_PROXY_NAMES)
        regrets = []
        for pmetrics in res["per_proxy"].values():
            for req_key in (
                "score",
                "acc",
                "wrong_rate",
                "abstain_rate",
                "mean_final_day",
                "paired_regret_vs_solver",
            ):
                assert req_key in pmetrics
            assert (
                pmetrics["acc"] + pmetrics["wrong_rate"] + pmetrics["abstain_rate"]
                == pytest.approx(1.0)
            )
            assert pmetrics["paired_regret_vs_solver"] == pytest.approx(
                res["solver_score"] - pmetrics["score"]
            )
            regrets.append(pmetrics["paired_regret_vs_solver"])
        assert res["worst_case_proxy_regret"] == pytest.approx(min(regrets))
        assert res["mean_proxy_regret"] == pytest.approx(sum(regrets) / len(regrets))

    assert def_res["feasible"] is True
    assert def_res["pareto_dominates_default"] is False
    assert ens_res["feasible"] is True
    assert ens_res["solver_acc"] >= 0.85
    assert ens_res["solver_score"] >= 0.50 * ens_res["baseline_solver_score"]
    assert ens_res["worst_case_proxy_regret"] > def_res["worst_case_proxy_regret"]
    assert ens_res["pareto_dominates_default"] is True

    silent_mole = {"name": "silent", "rules": [], "default": {"leak": "none", "frame": "random_peer"}}
    infeas = evaluate_proxy_ensemble(silent_mole, tier="medium", seeds=[6400, 6401])
    assert infeas["feasible"] is False
    assert infeas["pareto_dominates_default"] is False


def test_search_ensemble_strategies_smoke_and_cli_json(tmp_path, capsys):
    search_res = search_ensemble_strategies(
        n_mutations=4,
        seed=0,
        tier="medium",
        train_seeds=range(6400, 6407),
        holdout_seeds=range(6420, 6427),
        min_solver_acc=0.85,
    )
    assert search_res["train_seeds"] == list(range(6400, 6407))
    assert search_res["holdout_seeds"] == list(range(6420, 6427))
    assert len(search_res["train_leaderboard"]) >= 2
    ranked = search_res["holdout_leaderboard"]
    assert len(ranked) >= 1
    for idx, row in enumerate(ranked):
        assert row["rank"] == idx + 1
        assert row["feasible"] is True
        assert row["solver_acc"] >= 0.85
        MoleStrategy.from_json(row["strategy_json"])
    if len(ranked) >= 2:
        assert ranked[0]["worst_case_proxy_regret"] >= ranked[1]["worst_case_proxy_regret"]
    assert search_res["best_strategy"] == ranked[0]["strategy_json"]

    out_path = tmp_path / "ensemble_eval.json"
    rc = main(
        [
            "--tier",
            "hard",
            "--seeds",
            "6400-6405",
            "--min-solver-acc",
            "0.85",
            "--json",
            "--out",
            str(out_path),
        ]
    )
    assert rc == 0
    captured = capsys.readouterr().out
    parsed_stdout = json.loads(captured)
    parsed_file = json.loads(out_path.read_text(encoding="utf-8"))
    assert parsed_stdout == parsed_file
    assert parsed_stdout["tier"] == "hard"
    assert parsed_stdout["n_seeds"] == 6
    assert parsed_stdout["feasible"] is True
    assert parsed_stdout["pareto_dominates_default"] is True


def test_source_hygiene_zero_hash_and_zero_dashes():
    hash_char = chr(35)
    en_dash = "\u2013"
    em_dash = "\u2014"
    for rel in ("canary/forge/proxy_ensemble.py", "tests/test_proxy_ensemble.py"):
        txt = (ROOT / rel).read_text(encoding="utf-8")
        assert hash_char not in txt, rel
        assert en_dash not in txt, rel
        assert em_dash not in txt, rel
