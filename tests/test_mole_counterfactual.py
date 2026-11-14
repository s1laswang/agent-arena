from __future__ import annotations

import json

import pytest

from canary.analysis.accuse import audit_episode
from canary.env import Env
from canary.eval import run_episode
from canary.forge.rl_mole import RLMole, default_like_params
from canary.mole.counterfactual import (
    BUILTIN_CANDIDATES,
    ScheduleReplayPolicy,
    evaluate_counterfactual,
    inspect_observation_history,
    load_strategies_spec,
    load_v14_frontier_episodes,
    main,
    replay_episode_counterfactual,
    replay_schedule,
)
from canary.mole.dsl import DEFAULT_STRATEGY, MoleStrategy


CUSTOM_SHY_STRATEGY = MoleStrategy.from_json(BUILTIN_CANDIDATES["canary_shy_frame_decoy"])


def test_load_committed_v14_episodes():
    loaded_5 = load_v14_frontier_episodes(tier="hard", sources=("opencode", "inproc"), seeds=range(5))
    assert list(loaded_5["opencode"].keys()) == [0, 1, 2, 3, 4]
    assert list(loaded_5["inproc"].keys()) == [0, 1, 2, 3, 4]

    loaded_all = load_v14_frontier_episodes(tier="hard", sources=("opencode", "inproc"))
    assert len(loaded_all["opencode"]) == 30
    assert len(loaded_all["inproc"]) == 30


def test_schedule_replay_policy_matches_recorded_audit_and_never_accuses():
    opencode_eps = load_v14_frontier_episodes(tier="hard", sources=("opencode",), seeds=range(5))["opencode"]
    for seed, ep in opencode_eps.items():
        aud = audit_episode(ep)
        pol = ScheduleReplayPolicy(ep, target_day="accuse")
        env = Env("hard", seed, mole_strategy=DEFAULT_STRATEGY)
        history = replay_schedule(env, pol)

        assert not env.done
        assert env.verdict()["accused"] is None
        assert all(st.tool != "accuse" for st in history)

        obs_metrics = inspect_observation_history(
            history,
            tier="hard",
            seed=seed,
            recorded_accused=ep.accused,
        )
        assert obs_metrics["known_V"] == pytest.approx(env.visible_V())
        expected_ev = max(
            0.0,
            obs_metrics["max_posterior"] * obs_metrics["known_V"] - (1.0 - obs_metrics["max_posterior"]),
        )
        assert obs_metrics["optimal_ev"] == pytest.approx(expected_ev)
        assert round(obs_metrics["max_posterior"], 3) == aud["p_top"]
        assert round(obs_metrics["p_recorded_accused"], 3) == aud["p_accused"]

        env_via_eval = Env("hard", seed, mole_strategy=DEFAULT_STRATEGY)
        run_episode(env_via_eval, pol)
        assert [s.result for s in env_via_eval.history] == [s.result for s in history]


def test_schedule_replay_horizon_and_non_accused_episode():
    loaded = load_v14_frontier_episodes(tier="hard", sources=("opencode",), seeds=[0, 11])["opencode"]

    ep0 = loaded[0]
    assert ep0.final_day < 21
    pol_hor = ScheduleReplayPolicy(ep0, target_day="horizon")
    env_hor = Env("hard", 0, mole_strategy=DEFAULT_STRATEGY)
    hist_hor = replay_schedule(env_hor, pol_hor)
    assert not env_hor.done
    assert env_hor.day == 21

    cf0 = replay_episode_counterfactual(ep0, DEFAULT_STRATEGY)
    assert cf0["accuse_day"] == ep0.final_day
    assert cf0["horizon_day"] == 21
    assert cf0["surfaced_total_leaks_horizon"] >= cf0["surfaced_total_leaks"]
    assert cf0["surfaced_canaries_horizon"] >= cf0["surfaced_canaries"]
    assert len(hist_hor) > pol_hor.recorded_prefix_len

    ep11 = loaded[11]
    assert ep11.end_reason == "horizon"
    pol11 = ScheduleReplayPolicy(ep11, target_day=21)
    env11 = Env("hard", 11, mole_strategy=DEFAULT_STRATEGY)
    replay_schedule(env11, pol11)
    assert not env11.done
    assert env11.day == 21

    with pytest.raises(ValueError):
        ScheduleReplayPolicy(ep0, target_day=0)
    with pytest.raises(ValueError):
        ScheduleReplayPolicy(ep0, target_day=22)
    with pytest.raises(ValueError):
        ScheduleReplayPolicy(ep0, target_day="bad_target")


def test_evaluate_counterfactual_paired_opencode_and_live_solver():
    report = evaluate_counterfactual(
        strategies={
            "default_v0": DEFAULT_STRATEGY,
            "canary_shy_frame_decoy": CUSTOM_SHY_STRATEGY,
        },
        seeds=range(5),
        tier="hard",
        run_solver=True,
        sources=("opencode", "inproc"),
    )

    assert report["tier"] == "hard"
    assert report["seeds"] == [0, 1, 2, 3, 4]
    assert report["sources"] == ["opencode", "inproc"]

    base = report["strategies"]["default_v0"]
    shy = report["strategies"]["canary_shy_frame_decoy"]

    assert base["p_true_mole_drop"] == pytest.approx(0.0)
    assert base["optimal_ev_drop"] == pytest.approx(0.0)
    assert base["surfaced_canaries_delta"] == pytest.approx(0.0)
    assert base["surfaced_total_leaks_delta"] == pytest.approx(0.0)
    assert base["solver"]["score_delta"] == pytest.approx(0.0)
    assert base["solver"]["accuracy"] >= 0.80
    assert base["feasible"] is True

    oc_base = base["per_source"]["opencode"]
    oc_shy = shy["per_source"]["opencode"]
    assert oc_shy["p_true_mole"] < oc_base["p_true_mole"]
    assert oc_shy["p_true_mole_drop"] > 0.15
    assert shy["p_true_mole_drop"] > 0.30
    assert oc_shy["optimal_ev"] < oc_base["optimal_ev"]
    assert oc_shy["optimal_ev_drop"] > 0.25
    assert oc_shy["surfaced_canaries"] < oc_base["surfaced_canaries"]
    assert oc_shy["surfaced_canaries_delta"] < 0.0

    assert shy["solver"]["accuracy"] >= 0.75
    assert shy["feasible"] is True
    assert shy["counterfactual_gap"] > base["counterfactual_gap"]
    assert shy["counterfactual_gap_gain"] > 0.10

    implicit_base_report = evaluate_counterfactual(
        strategies={"canary_shy_frame_decoy": CUSTOM_SHY_STRATEGY},
        seeds=range(5),
        tier="hard",
        run_solver=False,
        sources=("opencode",),
    )
    assert implicit_base_report["strategies"]["canary_shy_frame_decoy"]["optimal_ev_drop"] == pytest.approx(
        oc_shy["optimal_ev_drop"]
    )


def test_cli_and_strategy_file_loading(tmp_path, capsys):
    hof_path = tmp_path / "cand.jsonl"
    hof_path.write_text(
        json.dumps({"rank": 1, "strategy_json": CUSTOM_SHY_STRATEGY.to_json()}) + "\n",
        encoding="utf-8",
    )
    loaded = load_strategies_spec(hof_path)
    assert "default_v0" in loaded
    assert "canary_shy_frame_decoy" in loaded

    rc_table = main(["--seeds", "0-2", "--sources", "opencode", "--strategy-file", str(hof_path), "--no-solver"])
    assert rc_table == 0
    table_out = capsys.readouterr().out
    assert "canary_shy_frame_decoy" in table_out
    assert "Counterfactual Frontier Replay" in table_out

    json_out_path = tmp_path / "report.json"
    rc_json = main([
        "--seeds",
        "0-1",
        "--sources",
        "opencode",
        "--no-solver",
        "--json",
        "--out",
        str(json_out_path),
    ])
    assert rc_json == 0
    capsys.readouterr()
    payload = json.loads(json_out_path.read_text(encoding="utf-8"))
    assert payload["seeds"] == [0, 1]
    assert "canary_shy_frame_decoy" in payload["strategies"]
    assert "frame_decoy_seeded" in payload["strategies"]


def test_rl_mole_and_min_solver_acc_threshold(tmp_path):
    rl = RLMole(default_like_params(seed=0), greedy=True, name="rl_default_like")
    rl_path = tmp_path / "rl_policy.json"
    rl_path.write_text(json.dumps(rl.to_json()), encoding="utf-8")
    loaded = load_strategies_spec(rl_path)
    assert "default_v0" in loaded
    assert "rl_default_like" in loaded

    report = evaluate_counterfactual(
        strategies=loaded,
        seeds=range(3),
        tier="hard",
        run_solver=True,
        sources=("opencode",),
        min_solver_acc=0.85,
    )
    row = report["strategies"]["rl_default_like"]
    assert row["solver"]["min_solver_acc"] == pytest.approx(0.85)
    assert row["strict_feasible"] == row["feasible"]

