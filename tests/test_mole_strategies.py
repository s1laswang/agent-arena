"""Tests for transcript-grounded Mole DSL strategies in canary.mole.strategies."""
from __future__ import annotations

import json

import pytest

from canary import forge_track
from canary.forge.mutate import validate_strategy
from canary.mole.counterfactual import evaluate_counterfactual, load_strategies_spec
from canary.mole.dsl import DEFAULT_STRATEGY, FEATURES, FRAME_SELECTORS, LEAK_SELECTORS, MAX_RULES, MoleStrategy
from canary.mole.evolve_v14 import behavior_hash, is_valid_rule_conds
from canary.mole.strategies import (
    DEFAULT_DEV_SEEDS,
    DEFAULT_MAX_LOGS_ACC,
    DEFAULT_MIN_SOLVER_ACC,
    STRATEGIES,
    STRATEGY_JSONS,
    STRATEGY_SPECS,
    TRANSCRIPT_STRATEGIES,
    all_strategies,
    all_strategy_jsons,
    export_hof_rows,
    get_strategy,
    get_strategy_json,
    get_strategy_spec,
    list_strategy_names,
    main,
    verify_all_strategies,
    verify_strategy_slice,
    write_hof_jsonl,
)


def test_catalog_dsl_validity_and_empirical_grounding():
    names = list_strategy_names()
    assert len(names) == 6
    assert list_strategy_names(include_default=True) == [DEFAULT_STRATEGY.name, *names]
    assert set(STRATEGIES.keys()) == set(names)
    assert set(TRANSCRIPT_STRATEGIES.keys()) == set(names)
    assert set(STRATEGY_JSONS.keys()) == set(names)
    assert len(all_strategies()) == 6
    assert len(all_strategies(include_default=True)) == 7
    assert len(all_strategy_jsons()) == 6
    assert len(all_strategy_jsons(include_default=True)) == 7
    assert get_strategy("default") == DEFAULT_STRATEGY
    assert get_strategy(DEFAULT_STRATEGY.name) == DEFAULT_STRATEGY

    seen_hashes: set[str] = set()
    default_bh = behavior_hash(DEFAULT_STRATEGY.to_json(), "hard")

    for name in names:
        spec = get_strategy_spec(name)
        strat = get_strategy(name)
        sj = get_strategy_json(name)
        sj["default"]["leak"] = "none"
        assert get_strategy_json(name)["default"]["leak"] != "none"

        assert isinstance(strat, MoleStrategy)
        assert strat.name == name
        assert 1 <= len(strat.rules) <= MAX_RULES
        assert MoleStrategy.from_json(json.loads(json.dumps(strat.to_json()))) == strat

        validated = validate_strategy({"rules": spec.strategy_json["rules"], "default": spec.strategy_json["default"]})
        assert len(validated["rules"]) == len(strat.rules)

        for rule in spec.strategy_json["rules"]:
            assert is_valid_rule_conds(rule["if"], "hard"), (name, rule)
            for feat, _, _ in rule["if"]:
                assert feat in FEATURES
            assert rule["then"]["leak"] in LEAK_SELECTORS
            assert rule["then"]["frame"] in FRAME_SELECTORS
            assert rule["then"]["frame"] != "decoy"

        assert spec.strategy_json["default"]["frame"] != "decoy"
        assert spec.empirical_finding
        assert spec.solver_catchability_rationale
        assert len(spec.empirical_anchors) >= 4

        bh = behavior_hash(spec.strategy_json, "hard")
        assert bh != default_bh
        assert bh not in seen_hashes
        seen_hashes.add(bh)

    with pytest.raises(KeyError):
        get_strategy("nonexistent_strategy")
    with pytest.raises(KeyError):
        get_strategy_spec("nonexistent_strategy")


def test_seed_hygiene_rejects_reserved_and_judge_seeds():
    for forbidden in ([0, 1], [29], [30_000], [800_000], [900_000]):
        with pytest.raises(ValueError):
            verify_strategy_slice("reactive_canary_lag", seeds=forbidden, workers=1)


FAST_DEV_SLICE = [6004]


def test_all_strategies_pass_solver_and_logs_only_gates_on_dev_slice():
    assert 10 <= len(DEFAULT_DEV_SEEDS) <= 20
    assert set(FAST_DEV_SLICE).issubset(set(DEFAULT_DEV_SEEDS))
    report = verify_all_strategies(
        tier="hard",
        seeds=FAST_DEV_SLICE,
        workers=1,
        min_solver_acc=DEFAULT_MIN_SOLVER_ACC,
        max_logs_acc=DEFAULT_MAX_LOGS_ACC,
    )
    assert report["n_strategies"] == 6
    assert report["n_passed"] == 6
    assert report["unique_behaviors"] is True
    assert report["all_passed"] is True

    for row in report["strategies"]:
        assert row["conds_valid"] is True, row
        assert row["solver_acc"] >= 0.85, row
        assert row["solver_score"] >= 0.50 * row["baseline_solver_score"], row
        assert row["logs_only_acc"] <= 0.10, row
        assert row["logs_only_score"] < 0.0, row
        assert row["passed"] is True, row


def test_counterfactual_frontier_drop_and_proxy_regret():
    cf = evaluate_counterfactual(
        strategies=TRANSCRIPT_STRATEGIES,
        seeds=range(1),
        tier="hard",
        run_solver=False,
        sources=("opencode", "inproc"),
    )
    for name, row in cf["strategies"].items():
        if name == DEFAULT_STRATEGY.name:
            continue
        assert row["p_true_mole_drop"] > 0.0, (name, row)
        assert row["optimal_ev_drop"] > 0.0, (name, row)

    synth_cf = cf["strategies"]["frontier_synthesis_v14"]
    assert synth_cf["p_true_mole_drop"] > 0.15
    assert synth_cf["optimal_ev_drop"] > 0.15

    proxy_slice = verify_strategy_slice(
        "reactive_canary_lag",
        tier="hard",
        seeds=FAST_DEV_SLICE,
        workers=1,
        include_proxies=True,
    )
    assert proxy_slice["passed"] is True
    assert proxy_slice["solver_acc"] >= 0.85
    assert proxy_slice["logs_only_acc"] <= 0.10
    assert proxy_slice["accuse_most_logs_acc"] <= 0.10
    assert proxy_slice["proxies"]["gemini_proxy"]["regret"] > 0.15
    assert proxy_slice["min_proxy_regret"] > 0.0


def test_hof_export_and_cli_roundtrip(tmp_path, capsys):
    hof_path = tmp_path / "strategies_v14.jsonl"
    written = write_hof_jsonl(hof_path)
    assert written == hof_path
    rows = export_hof_rows()
    assert len(rows) == 6

    loaded_ft_rows, loaded_ft_strats = forge_track.load(hof_path)
    assert len(loaded_ft_rows) == 6
    assert [s.name for s in loaded_ft_strats] == list(STRATEGY_SPECS.keys())

    loaded_cf = load_strategies_spec(hof_path)
    assert set(STRATEGY_SPECS.keys()).issubset(set(loaded_cf.keys()))

    rc_list = main(["--list", "--json"])
    assert rc_list == 0
    list_payload = json.loads(capsys.readouterr().out)
    assert len(list_payload) == 6

    rc_verify = main([
        "--verify",
        "--tier",
        "medium",
        "--strategy",
        "non_decoy_tiebreak_framer",
        "--seeds",
        "6004-6004",
        "--workers",
        "1",
        "--json",
    ])
    assert rc_verify == 0
    verify_payload = json.loads(capsys.readouterr().out)
    assert verify_payload["all_passed"] is True
    assert verify_payload["strategies"][0]["solver_acc"] >= 0.85
    assert verify_payload["strategies"][0]["logs_only_acc"] <= 0.10
