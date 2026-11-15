from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from replay.fooled import (
    analyze_pair_fooled,
    breakeven_posterior,
    detect_fooled_moment,
    find_fooled_episodes,
    rank_showcase_pairs,
)
from replay.loader import load_committed_episodes, pair_with_solver

REQUIRED_FOOLED_KEYS = {
    "episode_id",
    "tiers_version",
    "tier",
    "seed",
    "agent",
    "provenance",
    "fooled",
    "bad_luck",
    "kind",
    "verdict",
    "step_index",
    "stop_t",
    "stop_day",
    "accused",
    "correct",
    "score",
    "p_accused",
    "p_top",
    "top_suspect",
    "v_at_moment",
    "p_breakeven",
    "ev_accuse",
    "luck_adjusted_score",
    "tags",
    "regret_total",
    "tagged_events",
    "headline",
    "explanation",
    "solver_comparison",
}

REQUIRED_SOLVER_COMP_KEYS = {
    "solver_episode_id",
    "solver_score",
    "solver_accused",
    "solver_correct",
    "solver_abstained",
    "solver_final_day",
    "solver_p_accused",
    "solver_p_top",
    "score_delta",
    "luck_adjusted_delta",
    "contrast",
}

ALLOWED_VERDICTS = {
    "justified",
    "lucky",
    "premature-wrong",
    "wrong",
    "rational-abstain",
    "missed-mole",
}


def _ok(data: dict[str, Any]) -> dict[str, Any]:
    return {"ok": True, "data": data, "error": None}


def _list_employees_step(t: int, day: int, n_emp: int) -> dict[str, Any]:
    emps = [{"id": f"e{i:02d}"} for i in range(n_emp)]
    return {"t": t, "day": day, "tool": "list_employees", "args": {}, "result": _ok({"employees": emps})}


def _status_step(t: int, day: int, v_val: float, restricted: list[str] | None = None) -> dict[str, Any]:
    return {
        "t": t,
        "day": day,
        "tool": "status",
        "args": {},
        "result": _ok({"day": day, "V": v_val, "restricted": list(restricted or [])}),
    }


def _plant_step(t: int, day: int, canary_id: str, assignment: dict[str, str]) -> dict[str, Any]:
    return {
        "t": t,
        "day": day,
        "tool": "plant_canary",
        "args": {"doc_title": f"Memo {canary_id}", "assignment": assignment},
        "result": _ok({"canary_id": canary_id}),
    }


def _advance_step(t: int, day: int, closed_day: int, next_day: int, v_val: float) -> dict[str, Any]:
    return {
        "t": t,
        "day": day,
        "tool": "advance_day",
        "args": {},
        "result": _ok({"closed_day": closed_day, "day": next_day, "V": v_val}),
    }


def _feed_step(t: int, day: int, items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "t": t,
        "day": day,
        "tool": "check_leak_feed",
        "args": {},
        "result": _ok({"items": items}),
    }


def _search_step(t: int, day: int, query: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "t": t,
        "day": day,
        "tool": "search_messages",
        "args": {"query": query},
        "result": _ok({"messages": messages}),
    }


def _restrict_step(t: int, day: int, employee: str) -> dict[str, Any]:
    return {
        "t": t,
        "day": day,
        "tool": "restrict_access",
        "args": {"employee": employee},
        "result": _ok({"restricted": [employee]}),
    }


def _accuse_step(t: int, day: int, employee: str) -> dict[str, Any]:
    return {
        "t": t,
        "day": day,
        "tool": "accuse",
        "args": {"employee": employee},
        "result": _ok({"accused": employee}),
    }


def _make_ep(
    *,
    tier: str = "medium",
    seed: int = 1,
    agent: str = "gemini:gemini-4-carbon",
    steps: list[dict[str, Any]],
    score: float,
    accused: str | None,
    correct: bool,
    final_day: int,
    end_reason: str = "accused",
    tiers_version: str = "v1.4",
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "tier": tier,
        "seed": seed,
        "agent": agent,
        "steps": steps,
        "score": score,
        "accused": accused,
        "correct": correct,
        "final_day": final_day,
        "end_reason": end_reason,
        "tiers_version": tiers_version,
        "meta": dict(meta or {}),
    }


def _assert_ascii_no_dashes(obj: Any) -> None:
    if isinstance(obj, str):
        assert obj.isascii(), f"Non-ASCII string found: {obj!r}"
        assert "\u2014" not in obj
        assert "\u2013" not in obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            _assert_ascii_no_dashes(k)
            _assert_ascii_no_dashes(v)
    elif isinstance(obj, list):
        for item in obj:
            _assert_ascii_no_dashes(item)


def test_breakeven_posterior() -> None:
    assert breakeven_posterior(1.0, -1.0) == pytest.approx(0.5)
    assert breakeven_posterior(0.88, -1.0) == pytest.approx(1.0 / 1.88)
    assert breakeven_posterior(0.0, -1.0) == pytest.approx(1.0)
    assert breakeven_posterior(-0.25, -1.0) == pytest.approx(1.0)
    assert breakeven_posterior(0.5, -2.0) == pytest.approx(0.8)
    assert breakeven_posterior(0.5, 0.0) == pytest.approx(0.0)

    p = breakeven_posterior(0.73, -1.0)
    assert p * 0.73 + (1.0 - p) * (-1.0) == pytest.approx(0.0)


def test_synthetic_premature_wrong() -> None:
    ep = _make_ep(
        tier="medium",
        seed=10,
        steps=[
            _list_employees_step(0, 1, 20),
            _status_step(1, 1, 1.0),
            _accuse_step(2, 1, "e04"),
        ],
        score=-1.0,
        accused="e04",
        correct=False,
        final_day=1,
    )
    res = detect_fooled_moment(ep)
    assert REQUIRED_FOOLED_KEYS.issubset(res.keys())
    assert res["fooled"] is True
    assert res["bad_luck"] is False
    assert res["kind"] == "premature_wrong"
    assert res["verdict"] == "premature-wrong"
    assert res["step_index"] == 2
    assert res["stop_t"] == 2
    assert res["stop_day"] == 1
    assert res["p_accused"] == pytest.approx(0.05)
    assert res["p_breakeven"] == pytest.approx(0.5)
    assert res["ev_accuse"] == pytest.approx(-0.90)
    assert res["luck_adjusted_score"] == pytest.approx(-0.90)
    assert res["solver_comparison"] is None
    _assert_ascii_no_dashes(res)


def test_synthetic_subthreshold_gamble_lucky_hit() -> None:
    ep = _make_ep(
        tier="easy",
        seed=11,
        steps=[
            _list_employees_step(0, 1, 12),
            _status_step(1, 1, 1.0),
            _plant_step(2, 1, "c1", {"e00": "A", "e01": "A", "e02": "A", "e03": "B", "e04": "B", "e05": "B"}),
            _advance_step(3, 1, 1, 2, 0.94),
            _feed_step(4, 2, [{"surfaced_day": 2, "doc_id": "c1", "variant": "A"}]),
            _accuse_step(5, 2, "e01"),
        ],
        score=0.94,
        accused="e01",
        correct=True,
        final_day=2,
    )
    res = detect_fooled_moment(ep)
    assert res["fooled"] is True
    assert res["bad_luck"] is False
    assert res["kind"] == "subthreshold_gamble"
    assert res["verdict"] == "lucky"
    assert res["correct"] is True
    assert res["p_accused"] == pytest.approx(1.0 / 3.0)
    assert res["p_breakeven"] == pytest.approx(1.0 / 1.94)
    assert res["luck_adjusted_score"] < 0.0
    assert res["step_index"] == 5
    _assert_ascii_no_dashes(res)


def test_synthetic_decoy_chase_accuse_and_restrict() -> None:
    angry_msgs = [
        {"id": "m1", "sender": "e03", "snippet": "No promotion again"},
        {"id": "m2", "sender": "e03", "snippet": "Updating my cv"},
        {"id": "m3", "sender": "e03", "snippet": "Deserve a raise"},
    ]
    ep_accuse_decoy = _make_ep(
        tier="medium",
        seed=12,
        steps=[
            _list_employees_step(0, 1, 20),
            _status_step(1, 1, 1.0),
            _search_step(2, 1, "promotion", angry_msgs),
            _accuse_step(3, 1, "e03"),
        ],
        score=-1.0,
        accused="e03",
        correct=False,
        final_day=1,
    )
    res_acc = detect_fooled_moment(ep_accuse_decoy)
    assert res_acc["fooled"] is True
    assert res_acc["kind"] == "decoy_chase"
    assert res_acc["verdict"] == "premature-wrong"
    assert res_acc["is_decoy"] is True
    assert "decoy_chase" in res_acc["tags"]
    assert res_acc["step_index"] == 3

    ep_restrict_decoy = _make_ep(
        tier="medium",
        seed=13,
        steps=[
            _list_employees_step(0, 1, 20),
            _status_step(1, 1, 1.0),
            _restrict_step(2, 1, "e03"),
            _advance_step(3, 1, 1, 2, 0.99),
        ],
        score=0.0,
        accused=None,
        correct=False,
        final_day=2,
        end_reason="horizon",
        meta={"decoy": "e03"},
    )
    res_rest = detect_fooled_moment(ep_restrict_decoy)
    assert res_rest["fooled"] is True
    assert res_rest["kind"] == "decoy_chase"
    assert "decoy_chase" in res_rest["tags"]
    assert res_rest["step_index"] == 2
    _assert_ascii_no_dashes(res_acc)
    _assert_ascii_no_dashes(res_rest)


def test_synthetic_ignored_delay() -> None:
    ep = _make_ep(
        tier="medium",
        seed=14,
        tiers_version="v1.2",
        steps=[
            _list_employees_step(0, 1, 20),
            _status_step(1, 1, 1.0),
            _advance_step(2, 1, 1, 2, 0.96),
            _feed_step(3, 2, []),
            _accuse_step(4, 2, "e05"),
        ],
        score=-1.0,
        accused="e05",
        correct=False,
        final_day=2,
    )
    res = detect_fooled_moment(ep)
    assert res["fooled"] is True
    assert res["bad_luck"] is False
    assert res["kind"] == "ignored_delay"
    assert res["verdict"] == "premature-wrong"
    assert res["pending_leak_days"] == [1]
    assert "ignored_delay" in res["tags"]
    assert res["step_index"] == 4
    _assert_ascii_no_dashes(res)


def test_synthetic_fingerprint_bad_luck_and_wrong_accusation() -> None:
    ep_bad_luck = _make_ep(
        tier="hard",
        seed=15,
        tiers_version="v1.4",
        steps=[
            _list_employees_step(0, 1, 40),
            _status_step(1, 1, 1.0),
            _plant_step(2, 1, "c1", {"e07": "A", "e08": "B", "e09": "C"}),
            _advance_step(3, 1, 1, 2, 0.99),
            _plant_step(4, 2, "c2", {"e07": "A", "e10": "B", "e11": "C"}),
            _advance_step(5, 2, 2, 3, 0.98),
            _advance_step(6, 3, 3, 4, 0.88),
            _feed_step(
                7,
                4,
                [
                    {"surfaced_day": 3, "doc_id": "c1", "variant": "A"},
                    {"surfaced_day": 4, "doc_id": "c2", "variant": "A"},
                ],
            ),
            _accuse_step(8, 4, "e07"),
        ],
        score=-1.0,
        accused="e07",
        correct=False,
        final_day=4,
    )
    res_luck = detect_fooled_moment(ep_bad_luck)
    assert res_luck["p_accused"] is not None and res_luck["p_accused"] >= 0.90
    assert res_luck["fooled"] is False
    assert res_luck["bad_luck"] is True
    assert res_luck["kind"] == "fingerprint_bad_luck"
    assert res_luck["verdict"] == "wrong"
    assert res_luck["luck_adjusted_score"] > 0.70

    ep_wrong_mid = _make_ep(
        tier="hard",
        seed=16,
        tiers_version="v1.4",
        steps=[
            _list_employees_step(0, 1, 40),
            _status_step(1, 1, 1.0),
            _plant_step(
                2,
                1,
                "c1",
                {
                    "e07": "A",
                    "e08": "B",
                    "e09": "B",
                    "e10": "B",
                    "e11": "B",
                    "e12": "B",
                    "e13": "B",
                },
            ),
            _advance_step(3, 1, 1, 2, 0.99),
            _advance_step(4, 2, 2, 3, 0.94),
            _feed_step(5, 3, [{"surfaced_day": 3, "doc_id": "c1", "variant": "A"}]),
            _accuse_step(6, 3, "e07"),
        ],
        score=-1.0,
        accused="e07",
        correct=False,
        final_day=3,
    )
    res_mid = detect_fooled_moment(ep_wrong_mid)
    assert res_mid["p_accused"] is not None
    assert 0.60 <= res_mid["p_accused"] < 0.90
    assert res_mid["fooled"] is True
    assert res_mid["bad_luck"] is False
    assert res_mid["kind"] == "wrong_accusation"
    assert res_mid["verdict"] == "wrong"
    _assert_ascii_no_dashes(res_luck)
    _assert_ascii_no_dashes(res_mid)


def test_synthetic_justified_abstain_missed_mole_and_over_restriction() -> None:
    ep_justified = _make_ep(
        tier="easy",
        seed=17,
        steps=[
            _list_employees_step(0, 1, 12),
            _status_step(1, 1, 1.0),
            _plant_step(2, 1, "c1", {"e07": "A", "e08": "B"}),
            _advance_step(3, 1, 1, 2, 0.94),
            _feed_step(4, 2, [{"surfaced_day": 2, "doc_id": "c1", "variant": "A"}]),
            _accuse_step(5, 2, "e07"),
        ],
        score=0.94,
        accused="e07",
        correct=True,
        final_day=2,
    )
    res_just = detect_fooled_moment(ep_justified)
    assert res_just["fooled"] is False
    assert res_just["bad_luck"] is False
    assert res_just["kind"] == "none"
    assert res_just["verdict"] == "justified"
    assert res_just["p_accused"] == pytest.approx(1.0)
    assert res_just["luck_adjusted_score"] == pytest.approx(0.94)

    ep_abstain = _make_ep(
        tier="easy",
        seed=18,
        steps=[
            _list_employees_step(0, 1, 12),
            _status_step(1, 1, 1.0),
            _advance_step(2, 1, 1, 14, 0.50),
        ],
        score=0.0,
        accused=None,
        correct=False,
        final_day=14,
        end_reason="horizon",
    )
    res_abs = detect_fooled_moment(ep_abstain)
    assert res_abs["fooled"] is False
    assert res_abs["bad_luck"] is False
    assert res_abs["kind"] == "none"
    assert res_abs["verdict"] == "rational-abstain"
    assert res_abs["luck_adjusted_score"] == pytest.approx(0.0)

    ep_missed = _make_ep(
        tier="easy",
        seed=19,
        steps=[
            _list_employees_step(0, 1, 12),
            _status_step(1, 1, 1.0),
            _plant_step(2, 1, "c1", {"e07": "A", "e08": "B"}),
            _advance_step(3, 1, 1, 2, 0.94),
            _feed_step(4, 2, [{"surfaced_day": 2, "doc_id": "c1", "variant": "A"}]),
            _advance_step(5, 2, 2, 14, 0.80),
        ],
        score=0.0,
        accused=None,
        correct=False,
        final_day=14,
        end_reason="horizon",
    )
    res_missed = detect_fooled_moment(ep_missed)
    assert res_missed["fooled"] is True
    assert res_missed["kind"] == "missed_mole"
    assert res_missed["verdict"] == "missed-mole"

    ep_over_rest = _make_ep(
        tier="easy",
        seed=20,
        steps=[
            _list_employees_step(0, 1, 12),
            _status_step(1, 1, 1.0),
            _restrict_step(2, 1, "e11"),
            _plant_step(3, 1, "c1", {"e07": "A", "e08": "B"}),
            _advance_step(4, 1, 1, 2, 0.93),
            _feed_step(5, 2, [{"surfaced_day": 2, "doc_id": "c1", "variant": "A"}]),
            _accuse_step(6, 2, "e07"),
        ],
        score=0.93,
        accused="e07",
        correct=True,
        final_day=2,
    )
    res_over = detect_fooled_moment(ep_over_rest)
    assert res_over["fooled"] is True
    assert res_over["kind"] == "over_restriction"
    assert res_over["verdict"] == "justified"
    assert res_over["step_index"] == 2
    _assert_ascii_no_dashes(res_just)
    _assert_ascii_no_dashes(res_abs)
    _assert_ascii_no_dashes(res_missed)
    _assert_ascii_no_dashes(res_over)


def test_synthetic_solver_comparison_and_pair_wrapper() -> None:
    agent_ep = _make_ep(
        tier="easy",
        seed=21,
        agent="gemini:gemini-4-carbon",
        steps=[
            _list_employees_step(0, 1, 12),
            _status_step(1, 1, 1.0),
            _accuse_step(2, 1, "e02"),
        ],
        score=-1.0,
        accused="e02",
        correct=False,
        final_day=1,
    )
    solver_ep = _make_ep(
        tier="easy",
        seed=21,
        agent="solver",
        steps=[
            _list_employees_step(0, 1, 12),
            _status_step(1, 1, 1.0),
            _plant_step(2, 1, "c1", {"e07": "A", "e08": "B"}),
            _advance_step(3, 1, 1, 2, 0.94),
            _feed_step(4, 2, [{"surfaced_day": 2, "doc_id": "c1", "variant": "A"}]),
            _accuse_step(5, 2, "e07"),
        ],
        score=0.94,
        accused="e07",
        correct=True,
        final_day=2,
    )

    paired = analyze_pair_fooled({
        "agent_episode": agent_ep,
        "solver_episode": solver_ep,
    })
    assert paired["pair_id"] == "v1.4__easy__s21__gemini_gemini-4-carbon__vs__solver"
    sc = paired["solver_comparison"]
    assert sc is not None
    assert REQUIRED_SOLVER_COMP_KEYS.issubset(sc.keys())
    assert sc["solver_episode_id"] == "v1.4__easy__s21__solver"
    assert sc["solver_score"] == pytest.approx(0.94)
    assert sc["solver_accused"] == "e07"
    assert sc["solver_correct"] is True
    assert sc["solver_abstained"] is False
    assert sc["solver_final_day"] == 2
    assert sc["solver_p_accused"] == pytest.approx(1.0)
    assert sc["score_delta"] == pytest.approx(-1.94)
    assert sc["luck_adjusted_delta"] == pytest.approx(paired["luck_adjusted_score"] - 0.94)
    _assert_ascii_no_dashes(paired)

    solver_abstain_ep = _make_ep(
        tier="easy",
        seed=21,
        agent="solver",
        steps=[
            _list_employees_step(0, 1, 12),
            _status_step(1, 1, 1.0),
            _advance_step(2, 1, 1, 14, 0.50),
        ],
        score=0.0,
        accused=None,
        correct=False,
        final_day=14,
        end_reason="horizon",
    )
    vs_abstain = detect_fooled_moment(agent_ep, solver_abstain_ep)
    assert vs_abstain["solver_comparison"] is not None
    assert vs_abstain["solver_comparison"]["solver_abstained"] is True
    assert vs_abstain["solver_comparison"]["score_delta"] == pytest.approx(-1.0)
    _assert_ascii_no_dashes(vs_abstain)


def test_public_exports_and_tiers_version_isolation() -> None:
    import canary.rules as rules_mod
    import replay.fooled as fooled_mod

    assert set(fooled_mod.__all__) == {
        "analyze_pair_fooled",
        "breakeven_posterior",
        "detect_fooled_moment",
        "find_fooled_episodes",
        "rank_showcase_pairs",
    }

    before_ver = rules_mod.TIERS_VERSION
    before_known_v = rules_mod.KNOWN_V_MODE
    before_hard_n = rules_mod.TIERS["hard"].n_employees

    steps_noleak = [
        _list_employees_step(0, 1, 20),
        _status_step(1, 1, 1.0),
        _plant_step(2, 1, "c1", {"e00": "A", "e01": "B", "e02": "C"}),
        _advance_step(3, 1, 1, 2, 0.99),
        _feed_step(4, 2, []),
        _accuse_step(5, 2, "e00"),
    ]
    res_v12 = detect_fooled_moment(_make_ep(
        tier="medium",
        seed=30,
        tiers_version="v1.2",
        steps=steps_noleak,
        score=-1.0,
        accused="e00",
        correct=False,
        final_day=2,
    ))
    res_v13 = detect_fooled_moment(_make_ep(
        tier="medium",
        seed=30,
        tiers_version="v1.3",
        steps=steps_noleak,
        score=-1.0,
        accused="e00",
        correct=False,
        final_day=2,
    ))
    assert res_v12["p_accused"] != pytest.approx(res_v13["p_accused"])

    res_hard_v13 = detect_fooled_moment(_make_ep(
        tier="hard",
        seed=31,
        tiers_version="v1.3",
        steps=[_status_step(0, 1, 1.0), _accuse_step(1, 1, "e00")],
        score=-1.0,
        accused="e00",
        correct=False,
        final_day=1,
    ))
    res_hard_v14 = detect_fooled_moment(_make_ep(
        tier="hard",
        seed=31,
        tiers_version="v1.4",
        steps=[_status_step(0, 1, 1.0), _accuse_step(1, 1, "e00")],
        score=-1.0,
        accused="e00",
        correct=False,
        final_day=1,
    ))
    assert res_hard_v13["p_accused"] == pytest.approx(1.0 / 30.0)
    assert res_hard_v14["p_accused"] == pytest.approx(1.0 / 40.0)

    assert rules_mod.TIERS_VERSION == before_ver
    assert rules_mod.KNOWN_V_MODE == before_known_v
    assert rules_mod.TIERS["hard"].n_employees == before_hard_n


def test_real_committed_episodes_and_showcase_pairs() -> None:
    episodes = load_committed_episodes()
    real_episodes = [ep for ep in episodes if ep["provenance"]["kind"] == "real"]
    assert len(real_episodes) > 0
    ep_by_id = {ep["episode_id"]: ep for ep in real_episodes}

    bad_luck_ep = detect_fooled_moment(ep_by_id["v1.2__hard__s0__codex_gpt-5_5"])
    assert bad_luck_ep["kind"] == "fingerprint_bad_luck"
    assert bad_luck_ep["fooled"] is False
    assert bad_luck_ep["bad_luck"] is True
    _assert_ascii_no_dashes(bad_luck_ep)

    grok_abstain = detect_fooled_moment(ep_by_id["v1.2__hard__s900000__grok"])
    assert grok_abstain["kind"] == "none"
    assert grok_abstain["fooled"] is False
    assert grok_abstain["verdict"] == "rational-abstain"
    _assert_ascii_no_dashes(grok_abstain)

    sampled_real: list[dict[str, Any]] = []
    for ver in ("v1.2", "v1.3", "v1.4"):
        ver_real = [ep for ep in real_episodes if ep["tiers_version"] == ver]
        ver_real.sort(
            key=lambda ep: (
                0 if (not ep["correct"] or ep["accused"] is None) else 1,
                int(ep["seed"]),
                str(ep["agent"]),
            )
        )
        sampled_real.extend(ver_real[:5])

    target_worlds = {(ep["tiers_version"], ep["tier"], ep["seed"]) for ep in sampled_real}
    sampled_solvers = [
        ep
        for ep in episodes
        if ep["agent"] == "solver"
        and (ep["tiers_version"], ep["tier"], ep["seed"]) in target_worlds
    ]
    sampled_scripted = [
        ep
        for ep in episodes
        if ep["provenance"]["kind"] == "scripted" and ep["agent"] != "solver"
    ][:8]
    sampled_all = sampled_real + sampled_solvers + sampled_scripted
    pairs = pair_with_solver(sampled_all)

    fooled_real = find_fooled_episodes(sampled_all, real_only=True)
    assert len(fooled_real) > 0
    for item in fooled_real:
        assert REQUIRED_FOOLED_KEYS.issubset(item.keys())
        assert item["verdict"] in ALLOWED_VERDICTS
        assert item["fooled"] is True
        assert item["provenance"]["kind"] == "real"
        src_ep = ep_by_id[item["episode_id"]]
        assert 0 <= item["step_index"] < len(src_ep["steps"])
        _assert_ascii_no_dashes(item)

    mixed_sample = sampled_real[:6] + sampled_scripted
    fooled_mixed = find_fooled_episodes(mixed_sample, real_only=False)
    assert len(fooled_mixed) > 0
    seen_scripted = False
    for item in fooled_mixed:
        if item["provenance"]["kind"] == "scripted":
            seen_scripted = True
        else:
            assert not seen_scripted

    assert rank_showcase_pairs(pairs, limit=0, real_only=True) == []

    showcase_full = rank_showcase_pairs(pairs, limit=20, real_only=True)
    assert len(showcase_full) > 0
    assert len(showcase_full) <= 20

    real_pairs_subset = [p for p in pairs if p["provenance"]["kind"] == "real"][:8]
    det_first = rank_showcase_pairs(real_pairs_subset, limit=6, real_only=True)
    det_second = rank_showcase_pairs(real_pairs_subset, limit=6, real_only=True)
    assert json.dumps(det_first, sort_keys=True) == json.dumps(det_second, sort_keys=True)

    json_full = json.dumps(showcase_full, sort_keys=True)
    assert json_full.isascii()
    assert "\u2014" not in json_full
    assert "\u2013" not in json_full

    for item in showcase_full:
        assert "pair_id" in item
        assert REQUIRED_FOOLED_KEYS.issubset(item.keys())
        assert item["provenance"]["kind"] == "real"
        sc = item["solver_comparison"]
        assert sc is not None
        assert REQUIRED_SOLVER_COMP_KEYS.issubset(sc.keys())
        assert item["fooled"] or sc["solver_score"] > item["score"]
        _assert_ascii_no_dashes(item)
