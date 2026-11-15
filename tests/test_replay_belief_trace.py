from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary import rules
from canary.analysis.accuse import audit_episode
from canary.analysis.tags import to_result
from canary.solver.policy import SolverPolicy
from canary.solver.regret import attribute
from replay.belief_trace import _fast_attribute, compute_belief_trace, resolve_episode_params
from replay.loader import load_committed_episodes

TOP_TRACE_KEYS = {
    "tiers_version",
    "n_employees",
    "initial",
    "steps",
    "accuse_audit",
    "luck_adjusted_score",
    "decoy_inferred",
}

INITIAL_KEYS = {
    "step_index",
    "t",
    "day",
    "posterior",
    "p_top",
    "top_suspect",
    "known_v",
    "break_even_p",
}

STEP_KEYS = {
    "step_index",
    "t",
    "day",
    "tool",
    "posterior_before",
    "posterior",
    "p_top",
    "top_suspect",
    "p_top_before",
    "top_suspect_before",
    "known_v",
    "break_even_p",
    "regret",
    "tags",
}

ACCUSE_AUDIT_KEYS = {
    "step_index",
    "t",
    "day",
    "accused",
    "correct",
    "p_accused",
    "p_top",
    "top_suspect",
    "known_v",
    "v_for_luck",
    "break_even_p",
    "luck_adjusted_score",
    "verdict",
}


def _list_employees_step(t: int, day: int, n_employees: int) -> dict[str, Any]:
    return {
        "t": t,
        "day": day,
        "tool": "list_employees",
        "args": {},
        "result": {
            "ok": True,
            "data": {
                "employees": [
                    {
                        "id": f"e{k:02d}",
                        "name": f"Emp {k}",
                        "dept": "eng",
                        "role": "ic",
                    }
                    for k in range(n_employees)
                ]
            },
            "error": None,
        },
    }


def _assert_valid_posterior(post: dict[str, float], n_employees: int) -> None:
    assert len(post) == n_employees
    assert all(0.0 <= p <= 1.0 for p in post.values())
    assert sum(post.values()) == pytest.approx(1.0)


def test_resolve_episode_params_versions_tracks_and_fallback() -> None:
    assert resolve_episode_params({"tier": "hard", "tiers_version": "v1.2"}) == rules.TIERS_V13["hard"]
    assert resolve_episode_params({"tier": "hard", "tiers_version": "v1.3"}) == rules.TIERS_V13["hard"]
    assert resolve_episode_params({"tier": "hard", "tiers_version": "v1.4"}) == rules.TIERS["hard"]

    assert resolve_episode_params({"tier": "hard", "meta": {"tiers_version": "v1.2"}}) == rules.TIERS_V13["hard"]
    assert resolve_episode_params({"tier": "hard", "meta": {"tiers_version": "v1.3"}}) == rules.TIERS_V13["hard"]
    assert resolve_episode_params({"tier": "hard", "meta": {"tiers_version": "v1.4"}}) == rules.TIERS["hard"]

    assert resolve_episode_params({"tier": "hard_forge", "tiers_version": "v1.3"}).n_employees == 30
    assert resolve_episode_params({"tier": "hard_rl", "tiers_version": "v1.4"}).n_employees == 40

    ep_fallback_30 = {
        "tier": "hard",
        "steps": [_list_employees_step(0, 1, 30)],
    }
    assert resolve_episode_params(ep_fallback_30) == rules.TIERS_V13["hard"]
    tr_fallback_30 = compute_belief_trace(ep_fallback_30)
    assert tr_fallback_30["tiers_version"] == "v1.3"
    assert tr_fallback_30["n_employees"] == 30

    ep_fallback_40 = {
        "tier": "hard",
        "steps": [_list_employees_step(0, 1, 40)],
    }
    assert resolve_episode_params(ep_fallback_40) == rules.TIERS["hard"]
    tr_fallback_40 = compute_belief_trace(ep_fallback_40)
    assert tr_fallback_40["tiers_version"] == "v1.4"
    assert tr_fallback_40["n_employees"] == 40


@pytest.mark.parametrize(
    ("tier", "tiers_version", "expected_n"),
    [
        ("easy", "v1.4", 12),
        ("medium", "v1.4", 20),
        ("hard", "v1.3", 30),
        ("hard", "v1.4", 40),
    ],
)
def test_synthetic_uniform_initial_posterior_and_do_nothing(
    tier: str,
    tiers_version: str,
    expected_n: int,
) -> None:
    ep = {
        "tier": tier,
        "tiers_version": tiers_version,
        "seed": 0,
        "agent": "do_nothing",
        "steps": [],
        "score": 0.0,
        "accused": None,
        "correct": False,
        "final_day": 14,
        "end_reason": "horizon",
        "meta": {"V": 0.72},
    }
    trace = compute_belief_trace(ep)
    assert set(trace.keys()) == TOP_TRACE_KEYS
    assert trace["tiers_version"] == tiers_version
    assert trace["n_employees"] == expected_n
    assert trace["steps"] == []
    assert trace["accuse_audit"] is None
    assert trace["luck_adjusted_score"] == 0.0
    assert trace["decoy_inferred"] is None

    init = trace["initial"]
    assert set(init.keys()) == INITIAL_KEYS
    assert init["step_index"] == 0
    assert init["t"] == -1
    assert init["day"] == 1
    assert init["known_v"] == pytest.approx(1.0)
    assert init["break_even_p"] == pytest.approx(0.5)
    assert init["top_suspect"] == "e00"
    assert init["p_top"] == pytest.approx(1.0 / expected_n)
    _assert_valid_posterior(init["posterior"], expected_n)
    for k in range(expected_n):
        assert init["posterior"][f"e{k:02d}"] == pytest.approx(1.0 / expected_n)


def test_synthetic_canary_leak_narrows_posterior_and_justified_accusation() -> None:
    ep = {
        "tier": "easy",
        "tiers_version": "v1.4",
        "seed": 7,
        "agent": "solver",
        "steps": [
            _list_employees_step(0, 1, 12),
            {
                "t": 1,
                "day": 1,
                "tool": "plant_canary",
                "args": {
                    "doc_title": "Memo 1",
                    "assignment": {"e02": "A", "e05": "A", "e07": "B", "e09": "B"},
                },
                "result": {"ok": True, "data": {"canary_id": "c1"}, "error": None},
            },
            {
                "t": 2,
                "day": 1,
                "tool": "advance_day",
                "args": {},
                "result": {
                    "ok": True,
                    "data": {"closed_day": 1, "day": 2, "V": 0.94},
                    "error": None,
                },
            },
            {
                "t": 3,
                "day": 2,
                "tool": "check_leak_feed",
                "args": {},
                "result": {
                    "ok": True,
                    "data": {
                        "items": [{"surfaced_day": 2, "doc_id": "c1", "variant": "A"}]
                    },
                    "error": None,
                },
            },
            {
                "t": 4,
                "day": 2,
                "tool": "plant_canary",
                "args": {
                    "doc_title": "Memo 2",
                    "assignment": {"e02": "A", "e05": "B"},
                },
                "result": {"ok": True, "data": {"canary_id": "c2"}, "error": None},
            },
            {
                "t": 5,
                "day": 2,
                "tool": "advance_day",
                "args": {},
                "result": {
                    "ok": True,
                    "data": {"closed_day": 2, "day": 3, "V": 0.88},
                    "error": None,
                },
            },
            {
                "t": 6,
                "day": 3,
                "tool": "check_leak_feed",
                "args": {},
                "result": {
                    "ok": True,
                    "data": {
                        "items": [
                            {"surfaced_day": 2, "doc_id": "c1", "variant": "A"},
                            {"surfaced_day": 3, "doc_id": "c2", "variant": "B"},
                        ]
                    },
                    "error": None,
                },
            },
            {
                "t": 7,
                "day": 3,
                "tool": "accuse",
                "args": {"employee": "e05"},
                "result": {
                    "ok": True,
                    "data": {"accused": "e05", "episode_over": True},
                    "error": None,
                },
            },
        ],
        "score": 0.88,
        "accused": "e05",
        "correct": True,
        "final_day": 3,
        "end_reason": "accused",
        "meta": {"V": 0.88},
    }

    trace = compute_belief_trace(ep)
    assert len(trace["steps"]) == 8
    for st in trace["steps"]:
        assert set(st.keys()) == STEP_KEYS
        _assert_valid_posterior(st["posterior_before"], 12)
        _assert_valid_posterior(st["posterior"], 12)

    feed_step_1 = trace["steps"][3]
    assert feed_step_1["tool"] == "check_leak_feed"
    assert feed_step_1["posterior"]["e02"] == pytest.approx(0.5)
    assert feed_step_1["posterior"]["e05"] == pytest.approx(0.5)
    for k in range(12):
        emp = f"e{k:02d}"
        if emp not in {"e02", "e05"}:
            assert feed_step_1["posterior"][emp] == pytest.approx(0.0)
    assert feed_step_1["p_top"] == pytest.approx(0.5)
    assert feed_step_1["top_suspect"] == "e02"

    feed_step_2 = trace["steps"][6]
    assert feed_step_2["posterior"]["e05"] == pytest.approx(1.0)
    assert feed_step_2["p_top"] == pytest.approx(1.0)
    assert feed_step_2["top_suspect"] == "e05"

    accuse_step = trace["steps"][7]
    assert accuse_step["posterior_before"]["e05"] == pytest.approx(1.0)
    assert accuse_step["p_top_before"] == pytest.approx(1.0)
    assert accuse_step["top_suspect_before"] == "e05"
    assert accuse_step["known_v"] == pytest.approx(0.88)
    assert accuse_step["break_even_p"] == pytest.approx(1.0 / 1.88)

    audit = trace["accuse_audit"]
    assert audit is not None
    assert set(audit.keys()) == ACCUSE_AUDIT_KEYS
    assert audit["step_index"] == 8
    assert audit["t"] == 7
    assert audit["day"] == 3
    assert audit["accused"] == "e05"
    assert audit["correct"] is True
    assert audit["p_accused"] == pytest.approx(1.0)
    assert audit["p_accused"] >= audit["break_even_p"]
    assert audit["verdict"] == "justified"
    assert audit["v_for_luck"] == pytest.approx(0.88)
    assert audit["luck_adjusted_score"] == pytest.approx(0.88)
    assert trace["luck_adjusted_score"] == pytest.approx(0.88)


def test_synthetic_premature_wrong_lucky_and_wrong_justified_verdicts() -> None:
    base_steps = [
        _list_employees_step(0, 1, 20),
        {
            "t": 1,
            "day": 1,
            "tool": "accuse",
            "args": {"employee": "e04"},
            "result": {
                "ok": True,
                "data": {"accused": "e04", "episode_over": True},
                "error": None,
            },
        },
    ]

    ep_premature_wrong = {
        "tier": "medium",
        "tiers_version": "v1.4",
        "seed": 1,
        "agent": "stop_early",
        "steps": copy.deepcopy(base_steps),
        "score": -1.0,
        "accused": "e04",
        "correct": False,
        "final_day": 1,
        "end_reason": "accused",
        "meta": {"V": 1.0},
    }
    tr_wrong = compute_belief_trace(ep_premature_wrong)
    audit_wrong = tr_wrong["accuse_audit"]
    assert audit_wrong is not None
    assert audit_wrong["p_accused"] == pytest.approx(0.05)
    assert audit_wrong["break_even_p"] == pytest.approx(0.5)
    assert audit_wrong["p_accused"] < audit_wrong["break_even_p"]
    assert audit_wrong["verdict"] == "premature_wrong"
    assert tr_wrong["luck_adjusted_score"] == pytest.approx(0.05 * 1.0 - 0.95)
    assert tr_wrong["luck_adjusted_score"] < 0.0
    assert "premature_accusation" in tr_wrong["steps"][1]["tags"]
    assert tr_wrong["steps"][1]["regret"] > 0.0

    ep_lucky = {
        "tier": "medium",
        "tiers_version": "v1.4",
        "seed": 2,
        "agent": "stop_early",
        "steps": copy.deepcopy(base_steps),
        "score": 0.96,
        "accused": "e04",
        "correct": True,
        "final_day": 1,
        "end_reason": "accused",
        "meta": {"V": 1.0},
    }
    tr_lucky = compute_belief_trace(ep_lucky)
    audit_lucky = tr_lucky["accuse_audit"]
    assert audit_lucky is not None
    assert audit_lucky["correct"] is True
    assert audit_lucky["p_accused"] == pytest.approx(0.05)
    assert audit_lucky["p_accused"] < audit_lucky["break_even_p"]
    assert audit_lucky["verdict"] == "lucky"
    assert audit_lucky["v_for_luck"] == pytest.approx(0.96)
    assert tr_lucky["luck_adjusted_score"] == pytest.approx(0.05 * 0.96 - 0.95)
    assert tr_lucky["luck_adjusted_score"] < 0.0

    ep_wrong_justified = {
        "tier": "hard",
        "tiers_version": "v1.4",
        "seed": 3,
        "agent": "solver",
        "steps": [
            _list_employees_step(0, 1, 40),
            {
                "t": 1,
                "day": 1,
                "tool": "plant_canary",
                "args": {
                    "doc_title": "Hard trap 1",
                    "assignment": {"e11": "A", "e12": "B", "e13": "C"},
                },
                "result": {"ok": True, "data": {"canary_id": "c1"}, "error": None},
            },
            {
                "t": 2,
                "day": 1,
                "tool": "plant_canary",
                "args": {
                    "doc_title": "Hard trap 2",
                    "assignment": {"e11": "A", "e14": "B", "e15": "C"},
                },
                "result": {"ok": True, "data": {"canary_id": "c1-2"}, "error": None},
            },
            {
                "t": 3,
                "day": 1,
                "tool": "advance_day",
                "args": {},
                "result": {
                    "ok": True,
                    "data": {"closed_day": 1, "day": 2, "V": 0.98},
                    "error": None,
                },
            },
            {
                "t": 4,
                "day": 2,
                "tool": "advance_day",
                "args": {},
                "result": {
                    "ok": True,
                    "data": {"closed_day": 2, "day": 3, "V": 0.93},
                    "error": None,
                },
            },
            {
                "t": 5,
                "day": 3,
                "tool": "check_leak_feed",
                "args": {},
                "result": {
                    "ok": True,
                    "data": {
                        "items": [{"surfaced_day": 3, "doc_id": "c1", "variant": "A"}]
                    },
                    "error": None,
                },
            },
            {
                "t": 6,
                "day": 3,
                "tool": "accuse",
                "args": {"employee": "e11"},
                "result": {
                    "ok": True,
                    "data": {"accused": "e11", "episode_over": True},
                    "error": None,
                },
            },
        ],
        "score": -1.0,
        "accused": "e11",
        "correct": False,
        "final_day": 3,
        "end_reason": "accused",
        "meta": {"V_final": 0.88},
    }
    tr_wj = compute_belief_trace(ep_wrong_justified)
    audit_wj = tr_wj["accuse_audit"]
    assert audit_wj is not None
    assert audit_wj["correct"] is False
    assert audit_wj["p_accused"] >= audit_wj["break_even_p"]
    assert audit_wj["verdict"] == "wrong_justified"
    assert audit_wj["v_for_luck"] == pytest.approx(0.88)
    expected_wj = audit_wj["p_accused"] * 0.88 - (1.0 - audit_wj["p_accused"])
    assert tr_wj["luck_adjusted_score"] == pytest.approx(expected_wj)
    assert tr_wj["luck_adjusted_score"] > 0.0


def test_v_for_luck_precedence_decoy_inference_and_v12_leak_timing() -> None:
    accuse_only = [
        {
            "t": 0,
            "day": 1,
            "tool": "status",
            "args": {},
            "result": {"ok": True, "data": {"day": 1, "V": 0.80}, "error": None},
        },
        {
            "t": 1,
            "day": 1,
            "tool": "accuse",
            "args": {"employee": "e00"},
            "result": {
                "ok": True,
                "data": {"accused": "e00", "episode_over": True},
                "error": None,
            },
        },
    ]

    tr_vfinal_zero = compute_belief_trace({
        "tier": "easy",
        "tiers_version": "v1.4",
        "steps": copy.deepcopy(accuse_only),
        "score": -1.0,
        "accused": "e00",
        "correct": False,
        "meta": {"V_final": 0.0, "V": 0.75},
    })
    assert tr_vfinal_zero["accuse_audit"]["v_for_luck"] == pytest.approx(0.0)

    tr_known_fallback = compute_belief_trace({
        "tier": "easy",
        "tiers_version": "v1.4",
        "steps": copy.deepcopy(accuse_only),
        "score": -1.0,
        "accused": "e00",
        "correct": False,
        "meta": {},
    })
    assert tr_known_fallback["accuse_audit"]["v_for_luck"] == pytest.approx(0.80)

    ep_decoy = {
        "tier": "medium",
        "tiers_version": "v1.4",
        "steps": [
            {
                "t": 0,
                "day": 1,
                "tool": "search_messages",
                "args": {"query": "promotion"},
                "result": {
                    "ok": True,
                    "data": {
                        "messages": [
                            {"id": "m1", "sender": "e06"},
                            {"id": "m2", "sender": "e06"},
                            {"id": "m3", "sender": "e06"},
                        ]
                    },
                    "error": None,
                },
            }
        ],
    }
    tr_decoy = compute_belief_trace(ep_decoy)
    assert tr_decoy["decoy_inferred"] == "e06"
    assert tr_decoy["steps"][0]["posterior"]["e06"] == pytest.approx(0.0)
    _assert_valid_posterior(tr_decoy["steps"][0]["posterior"], 20)

    leak_timing_steps = [
        {
            "t": 0,
            "day": 1,
            "tool": "list_documents",
            "args": {"day_from": 1, "day_to": 1},
            "result": {
                "ok": True,
                "data": {
                    "documents": [
                        {
                            "doc_id": "d1-1",
                            "day": 1,
                            "recipients": ["e00", "e01"],
                            "is_canary": False,
                        }
                    ]
                },
                "error": None,
            },
        },
        {
            "t": 1,
            "day": 1,
            "tool": "advance_day",
            "args": {},
            "result": {
                "ok": True,
                "data": {"closed_day": 1, "day": 2, "V": 0.96},
                "error": None,
            },
        },
    ]
    tr_v12 = compute_belief_trace({
        "tier": "medium",
        "tiers_version": "v1.2",
        "steps": copy.deepcopy(leak_timing_steps),
    })
    tr_v13 = compute_belief_trace({
        "tier": "medium",
        "tiers_version": "v1.3",
        "steps": copy.deepcopy(leak_timing_steps),
    })
    assert tr_v12["steps"][1]["posterior"]["e00"] == pytest.approx(0.5)
    assert tr_v12["steps"][1]["posterior"]["e01"] == pytest.approx(0.5)
    assert tr_v13["steps"][1]["posterior"]["e00"] == pytest.approx(1.0 / 20.0)


@pytest.fixture(scope="module")
def committed_episodes() -> list[dict[str, Any]]:
    return load_committed_episodes()


def test_real_committed_episodes_across_v12_v13_v14(
    committed_episodes: list[dict[str, Any]],
) -> None:
    episodes = committed_episodes
    assert len(episodes) > 0

    selected: list[dict[str, Any]] = []
    seen_buckets: set[tuple[str, str, str]] = set()
    for ep in episodes:
        bucket = (ep["tiers_version"], ep["tier"], ep["provenance"]["kind"])
        if bucket not in seen_buckets:
            selected.append(ep)
            seen_buckets.add(bucket)
    abstained_ep = next((ep for ep in episodes if ep["accused"] is None), None)
    if abstained_ep is not None and abstained_ep not in selected:
        selected.append(abstained_ep)

    versions_seen = {ep["tiers_version"] for ep in selected}
    assert {"v1.2", "v1.3", "v1.4"}.issubset(versions_seen)
    assert any(ep["tiers_version"] == "v1.3" and ep["tier"] == "hard" for ep in selected)
    assert any(ep["tiers_version"] == "v1.4" and ep["tier"] == "hard" for ep in selected)

    determinism_checked = 0
    for ep in selected:
        ep_snapshot = copy.deepcopy(ep)
        tr1 = compute_belief_trace(ep)
        assert ep == ep_snapshot
        if determinism_checked < 3:
            tr2 = compute_belief_trace(ep)
            assert tr1 == tr2
            determinism_checked += 1

        ver = ep["tiers_version"]
        tier = ep["tier"]
        expected_n = (
            20
            if tier == "medium"
            else (30 if ver in ("v1.2", "v1.3") else 40)
        )
        assert tr1["tiers_version"] == ver
        assert tr1["n_employees"] == expected_n
        _assert_valid_posterior(tr1["initial"]["posterior"], expected_n)

        prev_post = tr1["initial"]["posterior"]
        for idx, st_trace in enumerate(tr1["steps"]):
            assert st_trace["step_index"] == idx + 1
            assert st_trace["posterior_before"] == prev_post
            _assert_valid_posterior(st_trace["posterior_before"], expected_n)
            _assert_valid_posterior(st_trace["posterior"], expected_n)
            assert 0.0 <= st_trace["break_even_p"] <= 1.0
            prev_post = st_trace["posterior"]

        with rules.tiers_version(ver):
            ref = audit_episode(to_result(ep))

        if ep["accused"] is None:
            assert tr1["accuse_audit"] is None
            assert tr1["luck_adjusted_score"] == 0.0
            assert ref["p_accused"] is None
        else:
            audit = tr1["accuse_audit"]
            assert audit is not None
            assert audit["accused"] == ep["accused"]
            assert audit["correct"] is bool(ep["correct"])
            assert audit["day"] == ref["day"]
            assert round(audit["p_accused"], 3) == ref["p_accused"]
            assert round(audit["p_top"], 3) == ref["p_top"]
            assert audit["verdict"] in {
                "justified",
                "lucky",
                "premature_wrong",
                "wrong_justified",
            }
            assert audit["luck_adjusted_score"] == pytest.approx(
                tr1["luck_adjusted_score"]
            )


def test_step_by_step_exact_parity_with_unoptimized_solver_policy(
    committed_episodes: list[dict[str, Any]],
) -> None:
    episodes = committed_episodes
    sample = [
        next(
            ep
            for ep in episodes
            if ep["tiers_version"] == "v1.2"
            and ep["tier"] == "hard"
            and ep["agent"] == "solver"
        ),
        next(
            ep
            for ep in episodes
            if ep["tiers_version"] == "v1.3"
            and ep["tier"] == "hard"
            and ep["agent"] == "codex:gpt-5.5"
        ),
        next(
            ep
            for ep in episodes
            if ep["tiers_version"] == "v1.4"
            and ep["tier"] == "hard"
            and ep["agent"] == "solver"
        ),
    ]
    for ep in sample:
        trace = compute_belief_trace(ep)
        params = resolve_episode_params(ep)
        leak_known = ep["tiers_version"] == "v1.2"
        sp = SolverPolicy(params, use_v_drops=leak_known)
        sp.obs.employees = [f"e{k:02d}" for k in range(params.n_employees)]
        sp.obs.leak_timing_known = leak_known
        er = to_result(ep)
        with rules.tiers_version(ep["tiers_version"]):
            assert _fast_attribute(er) == attribute(er)
        assert trace["initial"]["posterior"] == sp.belief()
        for st_obj, st_trace in zip(er.steps, trace["steps"], strict=True):
            assert st_trace["posterior_before"] == sp.belief()
            sp._ingest(st_obj)
            sp.obs.leak_timing_known = leak_known
            assert st_trace["posterior"] == sp.belief()
