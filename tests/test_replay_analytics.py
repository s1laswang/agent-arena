from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.rules import TIERS, TIERS_VERSION
import replay.analytics as analytics
from replay.analytics import (
    SCRIPTED_AGENTS,
    TIER_SORT_ORDER,
    aggregate_failure_tags,
    attribute_episode_regret,
    bootstrap_mean_ci,
    build_analytics_summary,
    build_gap_table,
    compute_episode_luck_stats,
    infer_provenance,
    infer_tiers_version,
    paired_bootstrap_ratio_ci,
    rank_featured_replays,
)
from replay.loader import load_committed_episodes, pair_with_solver

EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)

REQUIRED_GAP_ROW_KEYS = {
    "tiers_version",
    "tier",
    "agent",
    "provenance",
    "n",
    "invalid_n",
    "paired_n",
    "mean_score",
    "score_ci_low",
    "score_ci_high",
    "score_ci_halfwidth",
    "luck_adjusted_mean",
    "luck_mean_ci_low",
    "luck_mean_ci_high",
    "solver_paired_mean",
    "solver_score",
    "paired_delta",
    "score_delta",
    "ratio",
    "ci_low",
    "ci_high",
    "luck_adjusted_ratio",
    "luck_ci_low",
    "luck_ci_high",
    "accuracy",
    "accuracy_when_accused",
    "accuse_rate",
    "abstain_rate",
    "premature_accuse_rate",
    "mean_accuse_day",
    "mean_p_accused",
}

REQUIRED_FEATURED_KEYS = {
    "pair_id",
    "tiers_version",
    "tier",
    "seed",
    "agent_episode_id",
    "solver_episode_id",
    "agent",
    "provenance",
    "agent_score",
    "solver_score",
    "score_delta",
    "luck_adjusted_score",
    "fooled_step",
    "fooled_day",
    "fooled_kind",
    "fooled_headline",
}

REQUIRED_TAG_ROW_KEYS = {
    "tiers_version",
    "tier",
    "agent",
    "provenance",
    "n",
    "invalid_n",
    "mean_score",
    "regret_total",
    "regret_mean",
    "top_tags",
    "tags",
}


def _emp_steps(n_employees: int, v_val: float = 1.0) -> list[dict[str, Any]]:
    emps = [{"id": f"e{k:02d}", "dept": "eng", "clearance": 2} for k in range(n_employees)]
    return [
        {
            "t": 0,
            "day": 1,
            "tool": "status",
            "args": {},
            "result": {"ok": True, "data": {"day": 1, "V": v_val}, "error": None},
        },
        {
            "t": 1,
            "day": 1,
            "tool": "list_employees",
            "args": {},
            "result": {"ok": True, "data": {"employees": emps}, "error": None},
        },
    ]


def _assert_json_clean(payload: Any) -> str:
    text = json.dumps(payload, allow_nan=False)
    assert EM_DASH not in text
    assert EN_DASH not in text
    parsed = json.loads(text)
    assert parsed is not None
    return text


def test_exports_and_provenance_badges() -> None:
    expected_exports = {
        "REAL_PREFIXES",
        "SCRIPTED_AGENTS",
        "TIER_SORT_ORDER",
        "aggregate_failure_tags",
        "attribute_episode_regret",
        "bootstrap_mean_ci",
        "build_analytics_summary",
        "build_gap_table",
        "compute_episode_luck_stats",
        "infer_provenance",
        "infer_tiers_version",
        "paired_bootstrap_ratio_ci",
        "rank_featured_replays",
    }
    assert expected_exports.issubset(set(analytics.__all__))

    for name in ("solver", "heuristic", "do_nothing", "stop_early", "random", "restrict_all"):
        assert name in SCRIPTED_AGENTS
        prov = infer_provenance(name, {"meta": {"model": "ignored-model"}})
        assert prov == {"kind": "scripted", "label": "SCRIPTED", "model_id": name}

    assert infer_provenance("custom_bot", {"meta": {"provenance": "scripted"}}) == {
        "kind": "scripted",
        "label": "SCRIPTED",
        "model_id": "custom_bot",
    }

    assert infer_provenance("codex:gpt-5.5", {"meta": {"model": "gpt-5.5"}}) == {
        "kind": "real",
        "label": "REAL gpt-5.5",
        "model_id": "gpt-5.5",
    }
    assert infer_provenance("gemini:gemini-4-carbon") == {
        "kind": "real",
        "label": "REAL gemini:gemini-4-carbon",
        "model_id": "gemini:gemini-4-carbon",
    }
    assert infer_provenance("grok") == {
        "kind": "real",
        "label": "REAL grok",
        "model_id": "grok",
    }

    attached = {
        "provenance": {
            "kind": "real",
            "label": f"REAL gemini{EM_DASH}carbon",
            "model_id": "gemini-4-carbon",
        }
    }
    cleaned = infer_provenance("gemini:gemini-4-carbon", attached)
    assert cleaned == {
        "kind": "real",
        "label": "REAL gemini-carbon",
        "model_id": "gemini-4-carbon",
    }


def test_infer_tiers_version_precedence_and_staff_fallback() -> None:
    assert infer_tiers_version({"tier": "hard", "tiers_version": "v1.2"}) == "v1.2"
    assert infer_tiers_version({"tier": "hard", "meta": {"tiers_version": "v1.3"}}) == "v1.3"
    assert infer_tiers_version({"tier": "hard", "run_meta": {"tiers_version": "v1.2"}}) == "v1.2"

    ep_30 = {"tier": "hard", "steps": _emp_steps(30)}
    ep_40 = {"tier": "hard", "steps": _emp_steps(40)}
    assert infer_tiers_version(ep_30) == "v1.3"
    assert infer_tiers_version(ep_40) == TIERS_VERSION


def test_compute_episode_luck_stats_math_and_edge_cases() -> None:
    abstain_ep = {
        "tier": "medium",
        "seed": 0,
        "agent": "do_nothing",
        "steps": _emp_steps(20, v_val=0.76),
        "score": 0.0,
        "accused": None,
        "correct": False,
        "final_day": 14,
        "end_reason": "horizon",
        "meta": {"V": 0.76},
    }
    st_abstain = compute_episode_luck_stats(abstain_ep, "v1.4")
    assert st_abstain["abstained"] is True
    assert st_abstain["p_accused"] is None
    assert st_abstain["accuse_day"] is None
    assert st_abstain["luck_adjusted_score"] == 0.0
    assert st_abstain["premature"] is False
    assert st_abstain["p_top"] == pytest.approx(0.05)

    lucky_steps = _emp_steps(20, v_val=0.80) + [
        {
            "t": 2,
            "day": 3,
            "tool": "accuse",
            "args": {"employee": "e00"},
            "result": {"ok": True, "data": {"correct": True}, "error": None},
        }
    ]
    lucky_ep = {
        "tier": "medium",
        "seed": 1,
        "agent": "gemini:gemini-4-carbon",
        "steps": lucky_steps,
        "score": 0.80,
        "accused": "e00",
        "correct": True,
        "final_day": 3,
        "end_reason": "accused",
        "meta": {"V": 0.80},
    }
    st_lucky = compute_episode_luck_stats(lucky_ep, "v1.4")
    assert st_lucky["abstained"] is False
    assert st_lucky["accuse_day"] == 3
    assert st_lucky["p_accused"] == pytest.approx(0.05)
    assert st_lucky["break_even_p"] == pytest.approx(1.0 / 1.80)
    assert st_lucky["premature"] is True
    assert st_lucky["luck_adjusted_score"] == pytest.approx(0.05 * 0.80 - 0.95 * 1.0)

    wrong_ep = {
        "tier": "hard",
        "seed": 2,
        "agent": "openai:gpt-5.5",
        "steps": [],
        "score": -1.0,
        "accused": "e07",
        "correct": False,
        "final_day": 9,
        "end_reason": "accused",
        "p_accused": 0.25,
        "meta": {"V": 0.60},
    }
    st_wrong = compute_episode_luck_stats(wrong_ep, "v1.4")
    assert st_wrong["abstained"] is False
    assert st_wrong["accuse_day"] == 9
    assert st_wrong["p_accused"] == pytest.approx(0.25)
    assert st_wrong["break_even_p"] == pytest.approx(1.0 / 1.60)
    assert st_wrong["premature"] is True
    assert st_wrong["luck_adjusted_score"] == pytest.approx(0.25 * 0.60 - 0.75 * 1.0)

    justified_ep = {
        "tier": "hard",
        "seed": 3,
        "agent": "solver",
        "steps": [],
        "score": 0.70,
        "accused": "e11",
        "correct": True,
        "final_day": 12,
        "end_reason": "accused",
        "p_accused": 0.95,
        "meta": {"V": 0.70},
    }
    st_just = compute_episode_luck_stats(justified_ep, "v1.4")
    assert st_just["premature"] is False
    assert st_just["luck_adjusted_score"] == pytest.approx(0.95 * 0.70 - 0.05 * 1.0)


def test_bootstrap_cis_deterministic_and_edge_cases() -> None:
    assert bootstrap_mean_ci([]) == (None, None, None)
    assert bootstrap_mean_ci([0.62]) == (0.62, 0.62, 0.62)
    assert paired_bootstrap_ratio_ci([], []) == (None, None, None)
    assert paired_bootstrap_ratio_ci([0.5, 0.4], [0.0, 0.0]) == (None, None, None)
    assert paired_bootstrap_ratio_ci([0.62], [0.80]) == (0.775, 0.775, 0.775)

    with pytest.raises(ValueError):
        paired_bootstrap_ratio_ci([0.5], [0.5, 0.6])

    a_vals = [0.7, -1.0, 0.65, 0.8, 0.0, 0.55]
    s_vals = [0.8, 0.75, 0.7, 0.85, 0.6, 0.7]
    r1 = paired_bootstrap_ratio_ci(a_vals, s_vals, n_boot=1000, seed=42)
    r2 = paired_bootstrap_ratio_ci(a_vals, s_vals, n_boot=1000, seed=42)
    assert r1 == r2
    assert r1[0] is not None and r1[1] is not None and r1[2] is not None
    assert r1[1] <= r1[0] <= r1[2]

    m1 = bootstrap_mean_ci(a_vals, n_boot=1000, seed=42)
    m2 = bootstrap_mean_ci(a_vals, n_boot=1000, seed=42)
    assert m1 == m2
    assert m1[0] is not None and m1[1] is not None and m1[2] is not None
    assert m1[1] <= m1[0] <= m1[2]


def test_synthetic_gap_table_and_featured_replays() -> None:
    assert build_gap_table([]) == {"rows": []}
    assert rank_featured_replays([]) == []

    assert TIER_SORT_ORDER["hard"] < TIER_SORT_ORDER["hard_forge"] < TIER_SORT_ORDER["hard_rl"] < TIER_SORT_ORDER["medium"]

    episodes = [
        {
            "tiers_version": "v1.4",
            "tier": "hard",
            "seed": 0,
            "agent": "solver",
            "steps": [],
            "score": 0.80,
            "accused": "e01",
            "correct": True,
            "final_day": 10,
            "end_reason": "accused",
            "p_accused": 0.98,
            "meta": {"V": 0.80},
        },
        {
            "tiers_version": "v1.4",
            "tier": "hard",
            "seed": 0,
            "agent": "gemini:gemini-4-carbon",
            "steps": [
                {
                    "t": 4,
                    "day": 6,
                    "tool": "accuse",
                    "args": {"employee": "e09"},
                    "result": {"ok": True, "data": {"correct": False}, "error": None},
                }
            ],
            "score": -1.0,
            "accused": "e09",
            "correct": False,
            "final_day": 6,
            "end_reason": "accused",
            "p_accused": 0.20,
            "meta": {"V": 0.75, "decoy": "e09", "model": "gemini-4-carbon"},
            "fooled": {
                "headline": f"Chased decoy e09{EM_DASH}fell for angry messages{EN_DASH}early",
            },
        },
        {
            "tiers_version": "v1.4",
            "tier": "hard",
            "seed": 1,
            "agent": "gemini:gemini-4-carbon",
            "steps": [],
            "score": 0.0,
            "accused": None,
            "correct": False,
            "final_day": 1,
            "end_reason": "error",
            "valid": False,
            "meta": {"valid": False, "error": "quota"},
        },
        {
            "tiers_version": "v1.4",
            "tier": "hard",
            "seed": 0,
            "agent": "heuristic",
            "steps": [],
            "score": -1.0,
            "accused": "e02",
            "correct": False,
            "final_day": 5,
            "end_reason": "accused",
            "p_accused": 0.10,
            "meta": {"V": 0.80},
        },
        {
            "tiers_version": "v1.4",
            "tier": "hard_rl",
            "seed": 99,
            "agent": "grok",
            "steps": [],
            "score": 0.0,
            "accused": None,
            "correct": False,
            "final_day": 21,
            "end_reason": "horizon",
            "meta": {"V": 0.45},
        },
    ]

    gt = build_gap_table(episodes)
    _assert_json_clean(gt)
    rows = gt["rows"]
    assert len(rows) == 4
    assert [r["agent"] for r in rows] == ["solver", "gemini:gemini-4-carbon", "heuristic", "grok"]

    gem_row = rows[1]
    assert REQUIRED_GAP_ROW_KEYS.issubset(gem_row.keys())
    assert gem_row["n"] == 1
    assert gem_row["invalid_n"] == 1
    assert gem_row["paired_n"] == 1
    assert gem_row["provenance"] == {
        "kind": "real",
        "label": "REAL gemini-4-carbon",
        "model_id": "gemini-4-carbon",
    }
    assert gem_row["mean_score"] == -1.0
    assert gem_row["score_ci_halfwidth"] == 0.0
    assert gem_row["ratio"] == pytest.approx(-1.25)
    assert gem_row["accuse_rate"] == 1.0
    assert gem_row["abstain_rate"] == 0.0
    assert gem_row["accuracy"] == 0.0
    assert gem_row["accuracy_when_accused"] == 0.0
    assert gem_row["mean_accuse_day"] == 6.0
    assert gem_row["mean_p_accused"] == pytest.approx(0.20)

    grok_row = rows[3]
    assert grok_row["paired_n"] == 0
    assert grok_row["ratio"] is None
    assert grok_row["solver_paired_mean"] is None
    assert grok_row["abstain_rate"] == 1.0
    assert grok_row["accuse_rate"] == 0.0
    assert grok_row["accuracy_when_accused"] is None
    assert grok_row["mean_accuse_day"] is None
    assert grok_row["mean_p_accused"] is None

    synthetic_pairs = [
        {"agent_episode": episodes[1], "solver_episode": episodes[0]},
        {"agent_episode": episodes[3], "solver_episode": episodes[0]},
    ]
    assert rank_featured_replays(synthetic_pairs, limit=0) == []
    featured = rank_featured_replays(synthetic_pairs, limit=5)
    _assert_json_clean(featured)
    assert len(featured) == 2
    top = featured[0]
    assert REQUIRED_FEATURED_KEYS.issubset(top.keys())
    assert top["agent"] == "gemini:gemini-4-carbon"
    assert top["agent_episode_id"] == "v1.4__hard__s0__gemini_gemini-4-carbon"
    assert top["solver_episode_id"] == "v1.4__hard__s0__solver"
    assert top["pair_id"] == "v1.4__hard__s0__gemini_gemini-4-carbon__vs__solver"
    assert top["fooled_kind"] == "decoy_chase"
    assert EM_DASH not in (top["fooled_headline"] or "")
    assert EN_DASH not in (top["fooled_headline"] or "")


def test_failure_tags_versions_and_staff_sizes() -> None:
    assert aggregate_failure_tags([]) == {"rows": []}

    v13_ep = {
        "tiers_version": "v1.3",
        "tier": "hard",
        "seed": 0,
        "agent": "openai:gpt-5.5",
        "steps": _emp_steps(30, v_val=0.80)
        + [
            {
                "t": 2,
                "day": 2,
                "tool": "accuse",
                "args": {"employee": "e05"},
                "result": {"ok": True, "data": {"correct": False}, "error": None},
            }
        ],
        "score": -1.0,
        "accused": "e05",
        "correct": False,
        "final_day": 2,
        "end_reason": "accused",
        "meta": {"decoy": "e05", "model": "gpt-5.5"},
    }
    v14_ep = {
        "tiers_version": "v1.4",
        "tier": "hard",
        "seed": 0,
        "agent": "gemini:gemini-4-carbon",
        "steps": _emp_steps(40, v_val=0.85),
        "score": 0.0,
        "accused": None,
        "correct": False,
        "final_day": 21,
        "end_reason": "horizon",
        "meta": {"model": "gemini-4-carbon"},
    }

    items_v13 = attribute_episode_regret(v13_ep, "v1.3")
    items_v14 = attribute_episode_regret(v14_ep, "v1.4")
    assert TIERS["hard"].n_employees == 40
    assert items_v13[-1]["p_best"] == pytest.approx(round(1.0 / 30.0, 4))
    assert "premature_accusation" in items_v13[-1]["tags"]
    assert "decoy_chase" in items_v13[-1]["tags"]
    assert items_v14[-1]["p_best"] == pytest.approx(round(1.0 / 40.0, 4))
    assert items_v14[-1]["tags"] == ["no_accusation"]

    agg = aggregate_failure_tags([v13_ep, v14_ep])
    _assert_json_clean(agg)
    assert len(agg["rows"]) == 2
    by_ver = {r["tiers_version"]: r for r in agg["rows"]}

    r14 = by_ver["v1.4"]
    assert REQUIRED_TAG_ROW_KEYS.issubset(r14.keys())
    assert r14["provenance"]["kind"] == "real"
    assert r14["provenance"]["label"] == "REAL gemini-4-carbon"
    assert "no_accusation" in r14["tags"]
    assert r14["tags"]["no_accusation"]["rate"] == 1.0

    r13 = by_ver["v1.3"]
    assert r13["provenance"]["label"] == "REAL gpt-5.5"
    assert set(r13["tags"].keys()) == {"premature_accusation", "decoy_chase"}
    assert r13["tags"]["decoy_chase"]["worst"]["seed"] == 0
    assert r13["tags"]["decoy_chase"]["worst"]["args"] == {"employee": "e05"}


def test_real_committed_episodes_gap_featured_tags_and_json() -> None:
    all_eps = load_committed_episodes(include_invalid=True)
    valid_eps = [ep for ep in all_eps if ep["valid"]]
    pairs = pair_with_solver(all_eps)
    assert len(valid_eps) > 0
    assert len(pairs) > 0

    gt = build_gap_table(all_eps)
    _assert_json_clean(gt)
    rows = gt["rows"]
    assert len(rows) > 0

    versions_seen = {r["tiers_version"] for r in rows}
    assert {"v1.2", "v1.3", "v1.4"}.issubset(versions_seen)

    for r in rows:
        assert REQUIRED_GAP_ROW_KEYS.issubset(r.keys())
        assert r["n"] >= 1
        assert r["invalid_n"] >= 0
        assert 0.0 <= r["accuracy"] <= 1.0
        assert 0.0 <= r["accuse_rate"] <= 1.0
        assert 0.0 <= r["abstain_rate"] <= 1.0
        assert r["accuse_rate"] + r["abstain_rate"] == pytest.approx(1.0, abs=1e-3)
        if r["provenance"]["kind"] == "real":
            assert r["provenance"]["label"].startswith("REAL ")
        else:
            assert r["provenance"] == {
                "kind": "scripted",
                "label": "SCRIPTED",
                "model_id": r["agent"],
            }
        for v in r.values():
            if isinstance(v, float):
                assert math.isfinite(v)

    by_key = {(r["tiers_version"], r["tier"], r["agent"]): r for r in rows}
    codex_hard = by_key[("v1.3", "hard", "codex:gpt-5.5")]
    assert codex_hard["n"] == 11
    assert codex_hard["paired_n"] == 11
    assert codex_hard["mean_score"] == pytest.approx(0.6545, abs=1e-3)
    assert codex_hard["luck_adjusted_mean"] == pytest.approx(0.343, abs=1e-3)
    assert codex_hard["ratio"] is not None and codex_hard["ratio"] > 1.0
    assert codex_hard["luck_adjusted_ratio"] is not None and codex_hard["luck_adjusted_ratio"] < 0.85

    oc_hard = by_key[("v1.2", "hard", "opencode:openai/gpt-5.6-sol")]
    assert oc_hard["n"] == 1
    assert oc_hard["invalid_n"] == 4
    assert oc_hard["score_ci_halfwidth"] == 0.0

    featured = rank_featured_replays(pairs, limit=8)
    _assert_json_clean(featured)
    assert len(featured) == 8
    for item in featured:
        assert REQUIRED_FEATURED_KEYS.issubset(item.keys())
        assert item["provenance"]["kind"] == "real"
        assert item["provenance"]["label"].startswith("REAL ")
        assert item["pair_id"].endswith("__vs__solver")
        assert item["fooled_headline"]

    slice_eps = [
        ep
        for ep in all_eps
        if ep["seed"] in (0, 1)
        and ep["agent"] in ("solver", "codex:gpt-5.5", "openai:gpt-5.5", "do_nothing", "stop_early")
    ]
    summary = build_analytics_summary(slice_eps, featured_limit=4, include_failure_tags=True)
    _assert_json_clean(summary)
    tag_rows = summary["failure_tags"]["rows"]
    assert len(tag_rows) > 0
    assert {"v1.2", "v1.3", "v1.4"}.issubset({r["tiers_version"] for r in tag_rows})
    for tr in tag_rows:
        assert REQUIRED_TAG_ROW_KEYS.issubset(tr.keys())
        if tr["provenance"]["kind"] == "real":
            assert tr["provenance"]["label"].startswith("REAL ")
        else:
            assert tr["provenance"]["label"] == "SCRIPTED"
