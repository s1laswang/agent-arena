from __future__ import annotations

import io
import json
from pathlib import Path
import tokenize
from typing import Any

import pytest

import canary.arena.head_to_head as H2H
from canary.env import Env
from canary.mole.strategies import STRATEGIES, get_strategy_json
from canary.rules import HELDOUT_SEEDS, JUDGE_SEEDS, TRAIN_SEEDS
from canary.solver.policy import SolverPolicy

ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = ROOT / "canary" / "arena" / "head_to_head.py"
TEST_PATH = Path(__file__).resolve()


@pytest.mark.parametrize(
    "bad_seed",
    [
        min(JUDGE_SEEDS),
        max(JUDGE_SEEDS),
        min(HELDOUT_SEEDS),
        max(HELDOUT_SEEDS),
        min(TRAIN_SEEDS),
        0,
        4,
        26,
        30,
        2999,
        10000,
        -1,
        3000.0,
        3000.5,
        "3000.0",
        "3e3",
        True,
        False,
        None,
        "abc",
        [3000],
    ],
)
def test_seed_hygiene_rejects_benchmark_and_non_int_seeds(bad_seed: Any) -> None:
    with pytest.raises(ValueError):
        H2H.check_live_seed(bad_seed)
    with pytest.raises(ValueError):
        H2H.HeadToHeadSession("hard", bad_seed)


@pytest.mark.parametrize("bad_tier", ["easy", "hard_forge", "hard_rl", "", None, 42])
def test_tier_hygiene_rejects_unsupported_tiers(bad_tier: Any) -> None:
    with pytest.raises(ValueError):
        H2H.HeadToHeadSession(bad_tier, 3000)


def test_selectable_mole_opponents_and_create_session() -> None:
    catalog = H2H.list_mole_opponents()
    ids = {row["id"] for row in catalog}
    expected = {
        "default_v0",
        "frontier_synthesis_v14",
        "surgical_trap_shield",
        "gemini_midsize_shield",
        "early_burst_midgame_pace",
        "portfolio_v14",
        "rl_mole_frontier_v14",
    }
    assert expected <= ids
    for strat_name in STRATEGIES:
        assert strat_name in ids

    default_sess = H2H.create_session()
    assert default_sess.tier == "medium"
    assert default_sess.seed == 3000
    assert default_sess.mole_opponent == "frontier_synthesis_v14"
    assert default_sess.env.history == []

    for name in (
        "default_v0",
        "frontier_synthesis_v14",
        "surgical_trap_shield",
        "gemini_midsize_shield",
        "early_burst_midgame_pace",
        "portfolio_v14",
        "regret_portfolio",
        "rl_mole_frontier_v14",
    ):
        sess = H2H.HeadToHeadSession("hard", 3010, mole_opponent=name)
        assert sess.mole_opponent == name
        assert sess.mole_name == name
        assert sess.env.history == []

    s_kw = H2H.HeadToHeadSession(tier="medium", seed="3011", mole_strategy="surgical_trap_shield")
    assert s_kw.seed == 3011
    assert s_kw.mole_opponent == "surgical_trap_shield"

    s_json = H2H.HeadToHeadSession(tier="hard", seed=3012, mole_name=get_strategy_json("gemini_midsize_shield"))
    assert s_json.mole_opponent == "gemini_midsize_shield"

    with pytest.raises(ValueError):
        H2H.HeadToHeadSession("hard", 3010, mole_opponent="unknown_mole_xyz")

    with pytest.raises(ValueError):
        H2H.HeadToHeadSession("hard", 3010, mole_opponent="default_v0", mole_strategy="surgical_trap_shield")


def _collect_all_keys(obj: Any, out: set[str] | None = None) -> set[str]:
    if out is None:
        out = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.add(str(k))
            _collect_all_keys(v, out)
    elif isinstance(obj, list):
        for item in obj:
            _collect_all_keys(item, out)
    return out


def test_zero_hidden_tool_calls_and_zero_secret_leak_before_done() -> None:
    sess = H2H.HeadToHeadSession("hard", 3005, mole_opponent="frontier_synthesis_v14")
    true_mole = sess.env._world.mole
    decoy = sess.env._world.decoy

    assert len(sess.env.history) == 0
    st0 = sess.state_dict()
    snap0 = sess.snapshot(reveal=True)
    assert len(sess.env.history) == 0
    assert st0["mode"] == "head_to_head_live"
    assert st0["tool_calls"] == 0
    assert st0["done"] is False
    assert st0["reveal"] is None
    assert snap0["reveal"] is None
    assert st0["hud"]["known_v"] is None
    assert st0["hud"]["employees_discovered"] == 0
    assert len(st0["office_layout"]) == 40
    assert all(d["discovered"] is False and d["name"] is None for d in st0["office_layout"])
    assert true_mole not in json.dumps(st0)
    if decoy:
        assert decoy not in json.dumps(st0)

    with pytest.raises(ValueError):
        sess.reveal_dict()

    bad = sess.call_tool("interview", "{invalid json")
    assert bad["ok"] is False
    assert len(sess.env.history) == 0

    r1 = sess.call("status")
    assert r1["ok"] is True
    assert len(sess.env.history) == 1
    assert r1["state"]["hud"]["known_v"] == pytest.approx(1.0)

    r2 = sess.step("list_employees", {})
    assert r2["ok"] is True
    assert len(sess.env.history) == 2
    assert r2["state"]["hud"]["employees_discovered"] == 40
    assert all(d["discovered"] is True and d["name"] is not None for d in r2["state"]["office_layout"])

    sess.call_tool("list_documents", {"day_from": 1, "day_to": 1})
    sess.call_tool("check_leak_feed", {})
    sess.call_tool("interview", {"employee": "e00", "topic": "workload"})
    sess.call_tool("plant_canary", {"doc_title": "Audit Canary", "assignment": {"e00": "A", "e01": "B"}})
    sess.call_tool("advance_day", {})
    assert len(sess.env.history) == 7
    assert sess.env.done is False

    mid_state = sess.state_dict()
    assert mid_state["reveal"] is None
    assert mid_state["hud"]["interviews_count"] == 1
    assert mid_state["hud"]["planted_canaries"] == ["c1"]
    forbidden_keys = {"true_mole", "mole", "decoy", "opponents", "solver", "gemini_proxy", "gemini_carbon_proxy", "hinted_heuristic"}
    assert _collect_all_keys(mid_state).isdisjoint(forbidden_keys)
    json.dumps(mid_state)


def _solver_action_sequence(tier: str, seed: int) -> list[tuple[str, dict[str, Any]]]:
    env = Env(tier, seed)
    pol = SolverPolicy(tier)
    pol.reset(env.tools_spec(), env.instruction())
    acts: list[tuple[str, dict[str, Any]]] = []
    while not env.done:
        tool, args = pol.act(env.history)
        acts.append((tool, dict(args)))
        env.call(tool, args)
    return acts


def test_live_duel_solver_parity_and_cached_reveal() -> None:
    sess = H2H.HeadToHeadSession("medium", 3001, mole_opponent="default_v0")
    for tool, args in _solver_action_sequence("medium", 3001):
        out = sess.call_tool(tool, args)
    assert out["done"] is True
    assert sess.env.done is True
    assert out["state"]["reveal"] is not None

    rev = sess.reveal_dict()
    rev2 = sess.reveal_dict()
    assert rev == rev2
    json.dumps(rev)

    assert rev["true_mole"] == sess.env._world.mole
    assert rev["you"]["score"] == pytest.approx(rev["solver"]["score"])
    assert rev["you"]["accused"] == rev["solver"]["accused"]
    assert rev["you"]["posterior_curve"] == rev["solver"]["posterior_curve"]
    assert rev["winner_banner"] in ("MATCHED_SOLVER", "BEAT_SOLVER")
    assert "MATCHED_BAYESIAN_SOLVER" in rev["badges"]
    assert {"you", "solver", "gemini_proxy"} <= set(rev["daily_traces"])

    for key in ("human", "gemini_carbon_proxy", "solver", "hinted_heuristic"):
        summary = rev["opponents"][key]
        assert isinstance(summary["tool_calls"], int) and summary["tool_calls"] > 0
        for pt in summary["posterior_curve"]:
            assert 0.0 <= pt["p_true_mole"] <= 1.0

    assert len(rev["day_by_day"]) >= rev["you"]["final_day"]


def test_live_duel_hard_with_rl_mole_opponent() -> None:
    sess = H2H.HeadToHeadSession("hard", 3002, mole_strategy="rl_mole_frontier_v14")
    sess.call_tool("list_employees", {})
    sess.call_tool("status", {})
    sess.call_tool("accuse", {"employee": "e00"})
    assert sess.env.done is True

    rev = sess.reveal_dict()
    json.dumps(rev)
    assert rev["mole_opponent"] == "rl_mole_frontier_v14"
    assert {"you", "solver", "gemini_proxy"} <= set(rev)
    assert set(rev["opponents"]) == {"human", "gemini_carbon_proxy", "solver", "hinted_heuristic"}
    assert len(rev["daily_traces"]["you"]) == 1
    assert len(rev["daily_traces"]["gemini_proxy"]) >= 1
    assert len(rev["daily_traces"]["solver"]) >= 1


def test_ghost_replay_theater_real_committed_episodes_and_zero_env_probing(monkeypatch: pytest.MonkeyPatch) -> None:
    H2H._build_ghost_replay_cached.cache_clear()

    def _forbid_env(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Ghost replay theater must never instantiate live Env on benchmark seeds")

    monkeypatch.setattr(H2H, "Env", _forbid_env)
    monkeypatch.setattr("canary.env.Env.__init__", _forbid_env)

    listing = H2H.GhostReplayTheater.list_replays()
    ids = [row["replay_id"] for row in listing]
    assert ids == [
        "v14_hard_seed4_slow",
        "v14_hard_seed26_fooled",
        "v16_hard_seed30_cocktail",
        "v16_hard_seed31_cocktail",
        "v16_hard_seed32_cocktail",
    ]

    r4 = H2H.GhostReplayTheater.load("v14_hard_seed4_slow")
    json.dumps(r4)
    assert r4["seed"] == 4
    assert r4["tier"] == "hard"
    assert r4["true_mole"] == "e11"
    assert r4["left_agent"]["score"] == pytest.approx(0.73)
    assert r4["left_agent"]["final_day"] == 5
    assert r4["right_agent"]["score"] == pytest.approx(0.40)
    assert r4["right_agent"]["final_day"] == 16
    assert r4["solver_summary"]["score"] == pytest.approx(0.73)
    assert r4["gemini_summary"]["score"] == pytest.approx(0.40)
    assert any(d["highlight_tag"] == "SLOW_MOMENT" for d in r4["days"])
    assert r4["max_day"] == 16 and len(r4["days"]) == 16

    r26 = H2H.load_ghost_replay("v14_hard_seed26_fooled")
    json.dumps(r26)
    assert r26["seed"] == 26
    assert r26["true_mole"] == "e08"
    assert r26["left_agent"]["score"] == pytest.approx(0.69)
    assert r26["left_agent"]["final_day"] == 7
    assert r26["right_agent"]["score"] == pytest.approx(-1.00)
    assert r26["right_agent"]["final_day"] == 10
    assert r26["right_agent"]["accused"] == "e04"
    assert r26["days"][9]["highlight_tag"] == "FOOLED_MOMENT"
    assert r26["days"][9]["right"]["accused"] == "e04"

    for seed, rid, alias in (
        (30, "v16_hard_seed30_cocktail", "v16_social_seed30"),
        (31, "v16_hard_seed31_cocktail", "v16_social_seed31"),
        (32, "v16_hard_seed32_cocktail", "v16_social_seed32"),
    ):
        rs = H2H.load_ghost_replay(rid)
        rs_alias = H2H.load_ghost_replay(alias)
        json.dumps(rs)
        assert rs["seed"] == seed
        assert rs["replay_id"] == rid
        assert rs_alias["replay_id"] == rid
        assert len(rs["provenance_files"]) >= 2
        assert "gemini-4-carbon" in rs["right_agent"]["agent"]
        assert len(rs["days"]) == rs["max_day"]
        for day_row in rs["days"]:
            assert {"day", "left", "right", "commentary", "V", "canaries", "interviews", "p_true_mole"} <= set(day_row)
            assert 0.0 <= day_row["left"]["p_mole"] <= 1.0
            assert 0.0 <= day_row["right"]["p_mole"] <= 1.0

    with pytest.raises(ValueError):
        H2H.load_ghost_replay("nonexistent_replay_id")
    with pytest.raises(ValueError):
        H2H.load_ghost_replay(seed=999)


def test_source_hygiene_zero_comments_ascii_and_no_em_dashes() -> None:
    hash_char = chr(35)
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    for path in (MODULE_PATH, TEST_PATH):
        src = path.read_text(encoding="utf-8")
        assert src.isascii(), f"non-ASCII character in {path}"
        assert hash_char not in src, f"comment hash char in {path}"
        assert em_dash not in src and en_dash not in src, f"dash char in {path}"
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert comments == [], f"tokenize.COMMENT found in {path}"
