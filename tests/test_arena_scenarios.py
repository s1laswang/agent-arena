from __future__ import annotations

import io
import json
from pathlib import Path
import re
import socket
import sys
import tokenize
from typing import Any
import urllib.request

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.arena.be_the_mole import BeTheMoleSession
from canary.arena.head_to_head import HeadToHeadSession
from canary.arena.living_office import LivingOfficeSession
from canary.arena.scenarios import (
    ALLOWED_ARENA_MODES,
    ALLOWED_ARENA_TIERS,
    ARENA_SEED_MAX,
    ARENA_SEED_MIN,
    CURATED_SCENARIOS,
    ScenarioNotFoundError,
    SeedHygieneError,
    check_arena_seed,
    create_scenario_session,
    get_curated_scenario,
    list_curated_scenarios,
    list_modes,
    list_scenarios,
    validate_arena_seed,
    validate_seed,
)
from canary.env import Env
from canary.rules import HELDOUT_SEEDS, JUDGE_SEEDS, TRAIN_SEEDS

SCENARIOS_PATH = ROOT / "canary" / "arena" / "scenarios.py"
TEST_PATH = Path(__file__).resolve()

HASH_CHAR = chr(35)
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
UNICODE_MINUS = chr(0x2212)

FORBIDDEN_SUBSTRINGS: tuple[str, ...] = (
    "true_" + "mole",
    "mole_" + "id",
    "de" + "coy",
    "canary_" + "ids",
    "is_" + "mole",
    "is_de" + "coy",
    "sec" + "ret",
)

FORBIDDEN_DICT_KEYS: frozenset[str] = frozenset(
    {
        "true_" + "mole",
        "true_" + "mole_id",
        "mole_" + "id",
        "mole",
        "de" + "coy",
        "canary_" + "ids",
        "is_" + "mole",
        "is_de" + "coy",
        "sec" + "ret",
        "is_canary",
        "variants",
        "canary_xray",
        "bias_tags",
        "daily_p_mole",
        "select_weights",
        "mole_summary",
        "accused",
        "correct",
        "true_v",
        "reveal",
        "verdict",
        "xray",
        "primary_suspect",
        "secondary_suspect",
        "target_suspect",
    }
)

EMP_ID_PATTERN = re.compile(r"\be\d{2}\b")


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
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")

    def _deny_network(*args: Any, **kwargs: Any) -> None:
        raise AssertionError(f"network calls are forbidden in arena scenario tests: {args!r}")

    monkeypatch.setattr(socket.socket, "connect", _deny_network)
    monkeypatch.setattr(socket.socket, "connect_ex", _deny_network)
    monkeypatch.setattr(socket, "create_connection", _deny_network)
    monkeypatch.setattr(urllib.request, "urlopen", _deny_network)


def test_curated_scenarios_schema_and_diversity() -> None:
    assert 8 <= len(CURATED_SCENARIOS) <= 12
    assert list_modes() == ["be_the_mole", "head_to_head", "living_office"]
    assert list_scenarios() == list_curated_scenarios()

    all_rows = list_curated_scenarios()
    assert len(all_rows) == len(CURATED_SCENARIOS)

    seen_ids: set[str] = set()
    seen_seeds: set[int] = set()
    tiers_count = {"medium": 0, "hard": 0}
    modes_count = {m: 0 for m in ALLOWED_ARENA_MODES}
    categories: set[str] = set()

    required_keys = {
        "scenario_id",
        "id",
        "seed",
        "tier",
        "mode",
        "supported_modes",
        "category",
        "title",
        "subtitle",
        "narrative",
        "challenge_goal",
        "mole_opponent",
        "recommended_advisor",
        "variant",
        "social_variant",
        "difficulty_badge",
        "tags",
        "frontier_gap",
        "benchmark",
        "session_kwargs",
    }

    for sc in all_rows:
        assert required_keys.issubset(sc.keys())
        assert isinstance(sc["scenario_id"], str) and sc["scenario_id"]
        assert sc["id"] == sc["scenario_id"]
        assert sc["scenario_id"] not in seen_ids
        seen_ids.add(sc["scenario_id"])

        seed = sc["seed"]
        assert isinstance(seed, int) and not isinstance(seed, bool)
        assert 3000 <= seed <= 3059
        assert ARENA_SEED_MIN <= seed <= ARENA_SEED_MAX
        assert seed not in seen_seeds
        seen_seeds.add(seed)

        assert sc["tier"] in ALLOWED_ARENA_TIERS
        tiers_count[sc["tier"]] += 1

        assert sc["mode"] in ALLOWED_ARENA_MODES
        modes_count[sc["mode"]] += 1
        assert sc["supported_modes"] == list(ALLOWED_ARENA_MODES)
        categories.add(sc["category"])

        assert isinstance(sc["title"], str) and len(sc["title"]) >= 12
        assert isinstance(sc["subtitle"], str) and len(sc["subtitle"]) >= 20
        assert isinstance(sc["narrative"], str) and len(sc["narrative"]) >= 40
        assert isinstance(sc["challenge_goal"], str) and len(sc["challenge_goal"]) >= 20
        assert sc["variant"] == sc["social_variant"]
        assert isinstance(sc["tags"], list) and len(sc["tags"]) >= 3

        bm = sc["benchmark"]
        assert bm["selected_strategy"] == sc["mole_opponent"]
        assert bm["solver"]["solved"] is True
        assert bm["solver"]["score"] > 0.0
        assert bm["gemini_carbon_proxy"]["solved"] is False
        assert bm["logs_only"]["solved"] is False
        assert sc["frontier_gap"] == round(
            bm["solver"]["score"] - bm["gemini_carbon_proxy"]["score"], 2
        )
        assert sc["frontier_gap"] > 0.5

        encoded = json.dumps(sc, allow_nan=False)
        assert json.loads(encoded)["seed"] == seed

    assert tiers_count["medium"] >= 4
    assert tiers_count["hard"] >= 4
    for m in ALLOWED_ARENA_MODES:
        assert modes_count[m] >= 2
    assert len(categories) >= 4


def test_filtering_lookup_and_immutability() -> None:
    total = len(CURATED_SCENARIOS)
    by_mode_sum = 0
    for mode in ALLOWED_ARENA_MODES:
        m_rows = list_curated_scenarios(mode=mode)
        assert len(m_rows) >= 2
        assert all(r["mode"] == mode for r in m_rows)
        by_mode_sum += len(m_rows)
        for tier in ALLOWED_ARENA_TIERS:
            mt_rows = list_curated_scenarios(mode=mode, tier=tier)
            assert len(mt_rows) >= 1
            assert all(r["mode"] == mode and r["tier"] == tier for r in mt_rows)
    assert by_mode_sum == total

    med_rows = list_curated_scenarios(tier="medium")
    hard_rows = list_curated_scenarios(tier="hard")
    assert len(med_rows) + len(hard_rows) == total
    assert all(r["tier"] == "medium" for r in med_rows)
    assert all(r["tier"] == "hard" for r in hard_rows)

    for sc in CURATED_SCENARIOS:
        by_id = get_curated_scenario(sc["scenario_id"])
        by_seed = get_curated_scenario(sc["seed"])
        by_seed_str = get_curated_scenario(str(sc["seed"]))
        assert by_id == by_seed == by_seed_str
        by_id["title"] = "mutated"
        by_id["benchmark"]["solver"]["score"] = -999.0
        fresh = get_curated_scenario(sc["scenario_id"])
        assert fresh["title"] == sc["title"]
        assert fresh["benchmark"]["solver"]["score"] == sc["benchmark"]["solver"]["score"]

    first = CURATED_SCENARIOS[0]
    other_mode = next(m for m in ALLOWED_ARENA_MODES if m != first["mode"])
    other_tier = next(t for t in ALLOWED_ARENA_TIERS if t != first["tier"])
    with pytest.raises((KeyError, ValueError)):
        get_curated_scenario(first["scenario_id"], mode=other_mode)
    with pytest.raises((KeyError, ValueError)):
        get_curated_scenario(first["seed"], tier=other_tier)

    bad_modes: tuple[Any, ...] = ("invalid_mode", "", "BE_THE_MOLE", 123, True)
    for bad_mode in bad_modes:
        with pytest.raises(ValueError):
            list_curated_scenarios(mode=bad_mode)

    bad_tiers: tuple[Any, ...] = ("easy", "hard_forge", "MEDIUM", "", 123, True)
    for bad_tier in bad_tiers:
        with pytest.raises(ValueError):
            list_curated_scenarios(tier=bad_tier)

    with pytest.raises(ScenarioNotFoundError):
        get_curated_scenario("nonexistent_curated_scenario")
    with pytest.raises(ScenarioNotFoundError):
        get_curated_scenario(3999)
    with pytest.raises(KeyError):
        get_curated_scenario(3999)
    with pytest.raises(ValueError):
        get_curated_scenario(3999)


@pytest.mark.parametrize(
    "bad_seed",
    [
        True,
        False,
        0,
        4,
        26,
        29,
        30,
        2999,
        10000,
        30000,
        min(TRAIN_SEEDS),
        max(TRAIN_SEEDS),
        min(HELDOUT_SEEDS),
        max(HELDOUT_SEEDS),
        min(JUDGE_SEEDS),
        max(JUDGE_SEEDS),
        -1,
        -3000,
        3000.0,
        3000.5,
        float("nan"),
        float("inf"),
        "",
        "   ",
        "0",
        "30",
        "2999",
        "10000",
        "30000",
        "800000",
        "900000",
        None,
        [3000],
        {"seed": 3000},
    ],
)
def test_arena_seed_guard_enforces_3000_to_9999_and_rejects_bool(bad_seed: Any) -> None:
    for fn in (check_arena_seed, validate_arena_seed, validate_seed):
        with pytest.raises(SeedHygieneError):
            fn(bad_seed)
    with pytest.raises(ValueError):
        get_curated_scenario(bad_seed)


def test_arena_seed_guard_accepts_valid_boundaries() -> None:
    assert check_arena_seed(3000) == 3000
    assert check_arena_seed(3059) == 3059
    assert check_arena_seed(9999) == 9999
    assert check_arena_seed("3000") == 3000
    assert check_arena_seed(" +3020 ") == 3020


def test_zero_leak_invariant_across_code_dicts_and_live_worlds() -> None:
    raw_code = SCENARIOS_PATH.read_text(encoding="utf-8")
    low_code = raw_code.lower()
    for forbidden in FORBIDDEN_SUBSTRINGS:
        assert forbidden not in low_code, f"forbidden token {forbidden!r} found in scenarios.py"

    all_rows = list_curated_scenarios()
    raw_json = json.dumps(all_rows, allow_nan=False)
    low_json = raw_json.lower()
    for forbidden in FORBIDDEN_SUBSTRINGS:
        assert forbidden not in low_json, f"forbidden token {forbidden!r} found in serialized scenarios"

    collected_keys: set[str] = set()
    _collect_keys(all_rows, collected_keys)
    assert collected_keys.isdisjoint(FORBIDDEN_DICT_KEYS)
    assert EMP_ID_PATTERN.search(raw_json) is None

    for sc in all_rows:
        sc_json = json.dumps(sc, allow_nan=False)
        env = Env(sc["tier"], sc["seed"])
        world = env._world
        assert world.mole not in sc_json
        if world.decoy:
            assert world.decoy not in sc_json
        canary_doc_ids = [
            str(doc["id"])
            for doc in env._doc_by_id.values()
            if bool(doc.get("is_canary"))
        ]
        for cid in canary_doc_ids:
            assert f'"{cid}"' not in sc_json


def test_source_hygiene_on_scenarios_and_test_file() -> None:
    for path in (SCENARIOS_PATH, TEST_PATH):
        raw = path.read_text(encoding="utf-8")
        assert raw.isascii() is True
        assert HASH_CHAR not in raw
        assert EM_DASH not in raw
        assert EN_DASH not in raw
        assert UNICODE_MINUS not in raw
        tokens = list(tokenize.generate_tokens(io.StringIO(raw).readline))
        comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert comments == []


def test_compatibility_with_be_the_mole_head_to_head_and_living_office() -> None:
    for sc in list_curated_scenarios():
        btm = BeTheMoleSession(**sc["session_kwargs"]["be_the_mole"])
        assert btm.tier == sc["tier"]
        assert btm.seed == sc["seed"]
        st_btm = btm.state_dict()
        assert st_btm["done"] is False
        assert st_btm["reveal"] is None

        h2h = HeadToHeadSession(**sc["session_kwargs"]["head_to_head"])
        assert h2h.tier == sc["tier"]
        assert h2h.seed == sc["seed"]
        assert h2h.mole_opponent == sc["mole_opponent"]
        st_h2h = h2h.state_dict()
        assert st_h2h["done"] is False
        assert st_h2h.get("reveal") is None

        lo = LivingOfficeSession(**sc["session_kwargs"]["living_office"])
        assert lo.tier == sc["tier"]
        assert lo.seed == sc["seed"]
        assert lo.variant == sc["social_variant"]
        assert lo.mole_opponent == sc["mole_opponent"]
        st_lo = lo.state_dict()
        assert st_lo["done"] is False
        assert st_lo["verdict"] is None
        assert st_lo["xray"] is None

    btm_sess = create_scenario_session("medium_be_the_mole_synthesis_3000")
    assert isinstance(btm_sess, BeTheMoleSession)
    fin_btm = btm_sess.auto_play("frontier_synthesis_v14")
    assert fin_btm["done"] is True
    rev_btm = btm_sess.reveal_dict()
    sc_3000 = get_curated_scenario(3000)
    assert rev_btm["investigators"]["solver"]["score"] == sc_3000["benchmark"]["solver"]["score"]
    assert rev_btm["investigators"]["gemini_proxy"]["score"] == sc_3000["benchmark"]["gemini_carbon_proxy"]["score"]
    assert rev_btm["investigators"]["hinted_heuristic"]["score"] == sc_3000["benchmark"]["hinted_heuristic"]["score"]

    h2h_sess = create_scenario_session("medium_surgical_showdown_3038", mode="head_to_head")
    assert isinstance(h2h_sess, HeadToHeadSession)
    emp_res = h2h_sess.call_tool("list_employees", {})
    assert emp_res["ok"] is True
    first_emp = emp_res["data"]["employees"][0]["id"]
    acc_res = h2h_sess.call_tool("accuse", {"employee": first_emp})
    assert acc_res["done"] is True
    rev_h2h = h2h_sess.reveal_dict()
    assert isinstance(rev_h2h["true_mole"], str)

    lo_sess = create_scenario_session("medium_living_office_blackout_3023", mode="living_office")
    assert isinstance(lo_sess, LivingOfficeSession)
    step_res = lo_sess.step_auto_investigator("solver")
    assert step_res["policy"] == "solver"
    if not lo_sess.done:
        lo_sess.call_tool("accuse", {"employee": "e00"})
    assert lo_sess.done is True
    xray = lo_sess.bias_xray_dict()
    assert xray["variant"] == "v5_full9_cocktail"
