from __future__ import annotations

import json
from pathlib import Path
import socket
import sys
import tokenize
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.arena import be_the_mole as BTM
from canary.arena.be_the_mole import (
    MOLE_ADVISORS,
    BeTheMoleSession,
    check_arena_seed,
    create_session,
    list_mole_advisors,
)
from canary.env import Env
from canary.eval import run_episode
from canary.forge.frontier_proxies import GeminiCarbonProxy
from canary.forge.investigators import HintedHeuristic
from canary.forge.rl_mole import RLMole
from canary.mole.regret_portfolio import PortfolioMolePolicy
from canary.solver.policy import SolverPolicy

MODULE_PATH = ROOT / "canary" / "arena" / "be_the_mole.py"
TEST_PATH = Path(__file__).resolve()

EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
HASH_CHAR = chr(35)

FORBIDDEN_PRE_DONE_KEYS = frozenset(
    {
        "is_canary",
        "variants",
        "select_weights",
        "daily_p_mole",
        "canary_xray",
        "mole_summary",
        "accused",
        "correct",
        "true_v",
        "mole",
    }
)


def _collect_keys(obj: Any, out: set[str]) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.add(str(k))
            _collect_keys(v, out)
    elif isinstance(obj, list):
        for item in obj:
            _collect_keys(item, out)


@pytest.fixture(autouse=True)
def _keyless_and_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "")

    def _deny_connect(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("network socket calls are forbidden in arena tests")

    monkeypatch.setattr(socket.socket, "connect", _deny_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", _deny_connect)


def test_seed_and_tier_hygiene() -> None:
    invalid_seeds: list[Any] = [
        0,
        4,
        26,
        2999,
        10000,
        30000,
        800000,
        900000,
        True,
        False,
        -1,
        3000.5,
        "abc",
        "",
        None,
    ]
    for bad in invalid_seeds:
        with pytest.raises(ValueError):
            check_arena_seed(bad)
        with pytest.raises(ValueError):
            BeTheMoleSession("medium", bad)

    assert check_arena_seed(3000) == 3000
    assert check_arena_seed(9999) == 9999
    assert check_arena_seed("3042") == 3042

    for bad_tier in ("easy", "hard_forge", "hard_rl", "", "unknown"):
        with pytest.raises(ValueError):
            BeTheMoleSession(bad_tier, 3000)


def test_advisors_registry_and_metadata() -> None:
    required = {
        "default_v0",
        "frontier_synthesis_v14",
        "surgical_trap_shield",
        "gemini_midsize_shield",
        "early_burst_midgame_pace",
        "portfolio_v14",
        "rl_mole_frontier_v14",
    }
    assert required.issubset(set(MOLE_ADVISORS.keys()))
    assert isinstance(MOLE_ADVISORS["portfolio_v14"], PortfolioMolePolicy)
    assert isinstance(MOLE_ADVISORS["rl_mole_frontier_v14"], RLMole)

    advisors_meta = list_mole_advisors()
    assert len(advisors_meta) >= len(required)
    names = {row["name"] for row in advisors_meta}
    assert required.issubset(names)
    raw = json.dumps(advisors_meta)
    assert EM_DASH not in raw and EN_DASH not in raw


def test_zero_secret_leakage_before_done_and_midgame_case_closed() -> None:
    sess = create_session("medium", 3000)
    state = sess.state_dict()
    encoded = json.dumps(state)
    assert isinstance(encoded, str)
    assert state["mode"] == "be_the_mole"
    assert state["tier"] == "medium"
    assert state["seed"] == 3000
    assert state["day"] == 1
    assert state["max_days"] == 14
    assert state["done"] is False
    assert state["reveal"] is None

    with pytest.raises(ValueError):
        sess.reveal_dict()

    keys_day1: set[str] = set()
    _collect_keys(state, keys_day1)
    assert keys_day1.isdisjoint(FORBIDDEN_PRE_DONE_KEYS)

    mv = state["mole_view"]
    expected_mv_keys = {
        "day",
        "can_leak",
        "days_since_last_leak",
        "i_am_restricted",
        "n_restricted_colleagues",
        "recent_low_recipient_docs",
        "peers",
        "restricted_peers",
        "decoy",
        "docs",
    }
    assert set(mv.keys()) == expected_mv_keys
    for doc in mv["docs"]:
        assert set(doc.keys()) == {"doc_id", "title", "recipient_count", "age_days"}

    comp = state["company"]
    assert comp["player_mole_id"] not in mv["peers"]
    assert len(comp["employees"]) == 20
    assert comp["decoy_id"] == mv["decoy"]

    hints = state["advisor_hints"]
    assert set(hints.keys()) == {
        "frontier_synthesis_v14",
        "portfolio_v14",
        "rl_mole_frontier_v14",
    }
    for hint in hints.values():
        assert {"leak_choice", "frame_choice", "rationale"}.issubset(set(hint.keys()))
        assert isinstance(hint["rationale"], str) and hint["rationale"]

    mid_state = sess.auto_play("frontier_synthesis_v14", max_turns=4)
    assert mid_state["done"] is False
    assert mid_state["reveal"] is None
    assert mid_state["public_surface"]["investigator_status"]["solver"]["done"] is True
    assert mid_state["public_surface"]["investigator_status"]["solver"]["status"] == "case_closed"

    keys_mid: set[str] = set()
    _collect_keys(mid_state, keys_mid)
    assert keys_mid.isdisjoint(FORBIDDEN_PRE_DONE_KEYS)


def test_interactive_step_turn_choices_and_validation() -> None:
    sess = create_session("medium", 3001)
    st0 = sess.state_dict()
    docs0 = st0["mole_view"]["docs"]
    peers0 = st0["mole_view"]["peers"]
    player_id = st0["company"]["player_mole_id"]
    assert len(docs0) >= 1
    assert len(peers0) == 19

    with pytest.raises(ValueError):
        sess.step_turn(leak="nonexistent_doc_999", frame=None)
    assert sess.day == 1 and len(sess.turn_log) == 0

    with pytest.raises(ValueError):
        sess.step_turn(leak="none", frame="e99")
    with pytest.raises(ValueError):
        sess.step_turn(leak="none", frame=player_id)
    assert sess.day == 1 and len(sess.turn_log) == 0

    explicit_doc = docs0[0]["doc_id"]
    explicit_peer = peers0[0]
    st1 = sess.step_turn(leak=explicit_doc, frame=explicit_peer)
    assert st1["day"] == 2
    assert len(st1["turn_log"]) == 1
    log0 = st1["turn_log"][0]
    assert log0["day"] == 1
    if log0["can_leak"]:
        assert log0["leaked_doc_id"] == explicit_doc
    else:
        assert log0["leaked_doc_id"] is None
    assert log0["framed_peer_id"] == explicit_peer

    st2 = sess.step_turn(leak="none", frame="decoy")
    assert st2["day"] == 3
    assert st2["turn_log"][-1]["leaked_doc_id"] is None
    assert st2["turn_log"][-1]["framed_peer_id"] == st0["company"]["decoy_id"]

    st3 = sess.step_turn(leak="most_recipients", frame="random_peer")
    assert st3["day"] == 4
    assert len(st3["turn_log"]) == 3

    hard_sess = create_session("hard", 3002)
    hard_st = hard_sess.step_turn(leak="oldest", frame="none")
    assert hard_st["max_days"] == 21
    assert len(hard_st["company"]["employees"]) == 40
    assert "clearance" in hard_st["company"]["employees"][0]


def test_auto_play_reaches_done_and_matches_run_episode() -> None:
    sess = create_session("medium", 3000)
    final_state = sess.auto_play("frontier_synthesis_v14")
    assert final_state["done"] is True
    assert sess.done is True

    reveal = final_state["reveal"]
    assert reveal is not None
    assert set(reveal["investigators"].keys()) == {
        "gemini_proxy",
        "solver",
        "hinted_heuristic",
    }
    assert "FOOLED_GEMINI_FAIR_TO_SOLVER" in reveal["badges"]
    assert "OUTLASTED_GEMINI" in reveal["badges"]

    strat = MOLE_ADVISORS["frontier_synthesis_v14"]
    ref_agents = {
        "gemini_proxy": GeminiCarbonProxy(seed=3000),
        "solver": SolverPolicy("medium"),
        "hinted_heuristic": HintedHeuristic(seed=3000, n_days=14),
    }
    for inv_name, pol in ref_agents.items():
        ref = run_episode(Env("medium", 3000, mole_strategy=strat), pol)
        got = reveal["investigators"][inv_name]
        assert got["score"] == round(float(ref.score), 4)
        assert got["correct"] is bool(ref.correct)
        assert got["accused"] == ref.accused
        assert got["final_day"] == int(ref.final_day)
        assert got["tool_calls"] == len(ref.steps)
        assert len(got["daily_p_mole"]) == int(ref.final_day)
        assert all(0.0 <= p <= 1.0 for p in got["daily_p_mole"])

    ms = reveal["mole_summary"]
    assert ms["total_leaks"] == ms["canary_leaks_hit"] + ms["regular_leaks_hit"]
    assert len(reveal["canary_xray"]) == ms["total_leaks"]
    for item in reveal["canary_xray"]:
        assert item["doc_type"] in ("canary", "regular")
        assert isinstance(item["is_canary"], bool)

    bench = reveal["strategy_benchmark"]
    assert {"default_v0", "frontier_synthesis_v14", "player"}.issubset(set(bench.keys()))
    for row in bench.values():
        assert "gemini_proxy" in row and "solver" in row and "gap" in row

    with pytest.raises(ValueError):
        sess.step_turn(leak="none", frame="none")


def test_portfolio_and_rl_mole_advisors_and_hint_execution() -> None:
    sess = create_session("medium", 3003)
    for adv_name in ("frontier_synthesis_v14", "portfolio_v14", "rl_mole_frontier_v14"):
        st = sess.state_dict()
        if st["done"]:
            break
        hint = st["advisor_hints"][adv_name]
        sess.step_turn(leak=hint["leak_choice"], frame=hint["frame_choice"])

    fin_rl = sess.auto_play("rl_mole_frontier_v14")
    assert fin_rl["done"] is True
    assert fin_rl["reveal"] is not None

    port_sess = create_session("medium", 3004)
    fin_port = port_sess.auto_play("portfolio_v14")
    assert fin_port["done"] is True
    assert fin_port["reveal"] is not None


def test_zero_comments_and_zero_dashes() -> None:
    for path in (MODULE_PATH, TEST_PATH):
        text = path.read_text(encoding="utf-8")
        assert EM_DASH not in text, f"em dash found in {path}"
        assert EN_DASH not in text, f"en dash found in {path}"
        assert HASH_CHAR not in text, f"hash character found in {path}"
        with path.open("rb") as fh:
            tokens = list(tokenize.tokenize(fh.readline))
        comment_tokens = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert len(comment_tokens) == 0, f"comment token found in {path}"
        assert BTM is not None
