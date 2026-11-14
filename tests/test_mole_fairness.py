"""Tests for canary.mole.fairness_audit 7-check MoleStrategy and HOF fairness gate."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from canary.forge.rl_mole import RLMole, default_like_params
from canary.mole.dsl import DEFAULT_STRATEGY, MoleStrategy
from canary.mole.fairness_audit import (
    CHECK_NAMES,
    FAIRNESS_CHECK_NAMES,
    audit_hof,
    audit_strategy,
    main,
)

ROOT = Path(__file__).resolve().parent.parent
HOF_V13 = ROOT / "data" / "forge" / "hall_of_fame_v1.3.jsonl"


def test_default_strategy_passes_checks_1_to_6():
    res = audit_strategy(DEFAULT_STRATEGY, tier="hard", seeds=range(6000, 6020))
    assert tuple(res["checks"].keys()) == CHECK_NAMES
    for name in FAIRNESS_CHECK_NAMES:
        assert res["checks"][name]["passed"] is True, (name, res["checks"][name])
    assert res["fairness_passed"] is True

    c4 = res["checks"]["zero_baselines"]
    assert c4["do_nothing_scores_all_zero"] is True
    assert c4["stop_early_scores_all_zero"] is True
    assert c4["guess_day1_mean_score"] < 0.0

    c5 = res["checks"]["logs_only_bounded"]
    assert c5["logs_only_acc"] <= 0.20 and c5["logs_only_mean_score"] < 0.0
    assert c5["accuse_most_logs_acc"] <= 0.20 and c5["accuse_most_logs_mean_score"] < 0.0

    c6 = res["checks"]["solver_beatable"]
    assert c6["solver_acc"] >= 0.75
    assert c6["solver_mean_score"] >= 0.25

    c7 = res["checks"]["regret_gain"]
    assert set(c7["investigator_scores"].keys()) == {"heuristic", "hinted_heuristic", "grok_tactics"}
    assert c7["regret"] == pytest.approx(c7["default_regret"])
    assert c7["regret_gain"] == pytest.approx(0.0)
    assert c7["passed"] is False
    assert res["all_passed"] is False

    res_nonneg = audit_strategy(
        DEFAULT_STRATEGY, tier="hard", seeds=range(6000, 6005), min_regret_gain=0.0
    )
    assert res_nonneg["checks"]["regret_gain"]["passed"] is True
    assert res_nonneg["all_passed"] is True


def test_never_leaking_decoy_frame_fails_solver_beatable():
    unbeatable = {"rules": [], "default": {"leak": "none", "frame": "decoy"}}
    res = audit_strategy(unbeatable, tier="hard", seeds=range(6000, 6004))

    assert res["checks"]["dsl_valid"]["passed"] is True
    assert res["checks"]["no_tool_leak"]["passed"] is True
    assert res["checks"]["determinism"]["passed"] is True
    assert res["checks"]["zero_baselines"]["passed"] is True
    assert res["checks"]["logs_only_bounded"]["passed"] is True
    assert res["checks"]["solver_beatable"]["passed"] is False
    assert res["checks"]["solver_beatable"]["solver_acc"] < 0.75
    assert res["fairness_passed"] is False
    assert res["all_passed"] is False
    assert "solver_beatable" in res["failed_checks"]


def test_audit_hof_v13_runs_cleanly():
    rep = audit_hof("data/forge/hall_of_fame_v1.3.jsonl")
    assert rep["n_strategies"] == 1
    assert rep["n_passed"] == 1
    assert rep["n_fairness_passed"] == 1
    assert rep["fairness_passed"] is True
    assert rep["all_passed"] is True

    strat_rep = rep["strategies"][0]
    for name in CHECK_NAMES:
        assert strat_rep["checks"][name]["passed"] is True, (name, strat_rep["checks"][name])
    assert strat_rep["checks"]["regret_gain"]["regret_gain"] > 0.0
    serialized = json.dumps(rep, sort_keys=True)
    assert json.loads(serialized)["all_passed"] is True


@pytest.mark.parametrize(
    "bad_strategy",
    [
        None,
        "not_a_dict",
        {"rules": [{"if": [], "then": {"leak": "newest", "frame": "none"}}] * 13},
        {"rules": [{"if": [["mole_id", "==", 1]], "then": {"leak": "newest", "frame": "none"}}]},
        {"default": {"leak": "invalid_selector", "frame": "none"}},
        {"rules": [], "extra_key": 123},
        MoleStrategy(rules=(((), ("newest", "none")),) * 13),
    ],
)
def test_dsl_invalid_rejected_cleanly(bad_strategy):
    res = audit_strategy(bad_strategy, tier="hard", seeds=range(6000, 6004))
    assert res["all_passed"] is False
    assert res["fairness_passed"] is False
    assert res["checks"]["dsl_valid"]["passed"] is False
    assert res["checks"]["dsl_valid"]["error"]
    for name in CHECK_NAMES[1:]:
        assert res["checks"][name]["passed"] is False
        assert res["checks"][name].get("skipped") is True


def test_rl_mole_valid_and_nan_rejected():
    params = default_like_params(seed=0)
    rl_json = RLMole(params, name="rl_default_like").to_json()
    res = audit_strategy(rl_json, tier="hard", seeds=range(6000, 6005))
    assert res["strategy_kind"] == "rl_mole"
    for name in FAIRNESS_CHECK_NAMES:
        assert res["checks"][name]["passed"] is True, (name, res["checks"][name])

    bad_params = {k: v.copy() for k, v in params.items()}
    bad_params["W1"][0, 0] = np.nan
    bad_rl = RLMole(bad_params, name="rl_nan").to_json()
    bad_res = audit_strategy(bad_rl, tier="hard", seeds=range(6000, 6004))
    assert bad_res["checks"]["dsl_valid"]["passed"] is False
    assert bad_res["all_passed"] is False


def test_logs_only_bounded_catches_exposed_log_signal():
    res_easy = audit_strategy(DEFAULT_STRATEGY, tier="easy", seeds=range(6000, 6006))
    assert res_easy["checks"]["logs_only_bounded"]["passed"] is False
    assert res_easy["fairness_passed"] is False


def test_cli_and_mixed_hof(tmp_path, capsys):
    out_json = tmp_path / "audit_v13.json"
    rc = main(
        [
            "--hof",
            str(HOF_V13),
            "--tier",
            "hard",
            "--seeds",
            "6015-6019",
            "--out",
            str(out_json),
        ]
    )
    captured = capsys.readouterr()
    assert rc == 0
    stdout_rep = json.loads(captured.out)
    file_rep = json.loads(out_json.read_text(encoding="utf-8"))
    assert stdout_rep["all_passed"] is True
    assert file_rep == stdout_rep

    mixed_hof = tmp_path / "mixed.jsonl"
    v13_line = HOF_V13.read_text(encoding="utf-8").strip()
    bad_line = json.dumps(
        {"rank": 2, "strategy_json": {"rules": [], "default": {"leak": "none", "frame": "decoy"}}}
    )
    mixed_hof.write_text(v13_line + "\n" + bad_line + "\n", encoding="utf-8")

    rc_mixed = main(["--hof", str(mixed_hof), "--tier", "hard", "--seeds", "6015-6017"])
    mixed_out = json.loads(capsys.readouterr().out)
    assert rc_mixed == 1
    assert mixed_out["n_strategies"] == 2
    assert mixed_out["n_passed"] == 1
    assert mixed_out["all_passed"] is False

    empty_hof = tmp_path / "empty.jsonl"
    empty_hof.write_text("\n", encoding="utf-8")
    empty_rep = audit_hof(empty_hof, seeds=range(6000, 6004))
    assert empty_rep["all_passed"] is False
    assert empty_rep["n_strategies"] == 0

    with pytest.raises(FileNotFoundError):
        audit_hof(tmp_path / "missing.jsonl", seeds=range(6000, 6004))
