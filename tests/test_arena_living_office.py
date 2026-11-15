from __future__ import annotations

import io
import json
from pathlib import Path
import socket
import tokenize
import urllib.request

import pytest

from canary.arena.living_office import (
    BIAS_TYPES,
    GATE_B_DISCLOSURE,
    KEY_VARIANTS,
    LivingOfficeSession,
    list_living_office_variants,
    list_mole_opponents,
    list_v16_checkpoint_replays,
    load_v16_checkpoint_replay,
)

EXPECTED_BIASES = (
    "authority",
    "recency",
    "confirmation",
    "bandwagon",
    "anchoring",
    "grudge",
    "misforward",
    "false_memory",
    "sycophancy",
)

EXPECTED_PARTIAL_EPISODES = (
    ("v0_v14_control", 30),
    ("v0_v14_control", 31),
    ("v0_v14_control", 32),
    ("v0_v14_control", 33),
    ("v1_anchoring_authority_confirmation", 30),
    ("v3_grudge_falsemem_misforward", 30),
    ("v3_grudge_falsemem_misforward", 31),
    ("v5_full9_cocktail", 30),
    ("v5_full9_cocktail", 31),
    ("v5_full9_cocktail", 32),
)


@pytest.fixture(autouse=True)
def _enforce_zero_network_and_keyless(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "")

    def _forbid_network(*args: object, **kwargs: object) -> None:
        raise AssertionError(f"unexpected network call: {args!r} {kwargs!r}")

    monkeypatch.setattr(socket, "create_connection", _forbid_network)
    monkeypatch.setattr(urllib.request, "urlopen", _forbid_network)


def test_variants_metadata_and_gate_b_disclosure() -> None:
    variants = list_living_office_variants()
    assert [row["variant"] for row in variants] == list(KEY_VARIANTS)
    assert BIAS_TYPES == EXPECTED_BIASES

    by_name = {row["variant"]: row for row in variants}
    v5 = by_name["v5_full9_cocktail"]
    assert v5["control"] is False
    assert tuple(v5["biases"]) == EXPECTED_BIASES
    assert v5["provenance_badge_live"] == "v16-template-live"
    assert v5["checkpoint_seeds"] == [30, 31, 32]

    v0 = by_name["v0_v14_control"]
    assert v0["control"] is True
    assert v0["biases"] == []
    assert v0["provenance_badge_live"] == "v14-control"
    assert v0["checkpoint_seeds"] == [30, 31, 32, 33]

    for tok in ("v5_full9_cocktail", "n=3", "0.452", "0.493", "-0.041", "negative result"):
        assert tok in GATE_B_DISCLOSURE
        assert tok in v5["gate_b_disclosure"]


def test_seed_tier_and_variant_hygiene() -> None:
    for bad_seed in (30, 4, 0, -5, 2999, 10000, 30000, 800000, 900000, True, False, 3000.5, "bad"):
        with pytest.raises(ValueError):
            LivingOfficeSession(tier="medium", seed=bad_seed)

    for bad_tier in ("easy", "unknown", ""):
        with pytest.raises(ValueError):
            LivingOfficeSession(tier=bad_tier, seed=3000)

    with pytest.raises(ValueError):
        LivingOfficeSession(tier="medium", seed=3000, variant="nonexistent_variant")

    with pytest.raises(ValueError):
        LivingOfficeSession(tier="medium", seed=3000, mole_opponent="nonexistent_mole")

    s_lo = LivingOfficeSession(tier="medium", seed=3000, variant="v0_v14_control")
    s_hi = LivingOfficeSession(tier="hard", seed=9999, variant="v5_full9_cocktail")
    assert s_lo.state_dict()["provenance_badge"] == "v14-control"
    assert s_hi.state_dict()["provenance_badge"] == "v16-template-live"

    for bad_replay_seed in (4, 29, 34, 3000, 800000, 900000, True, False):
        with pytest.raises(ValueError):
            load_v16_checkpoint_replay("v5_full9_cocktail", bad_replay_seed)

    with pytest.raises(ValueError):
        load_v16_checkpoint_replay("v2_recency_bandwagon_sycophancy", 30)


def test_all_10_committed_checkpoint_replays_and_xray() -> None:
    listing = list_v16_checkpoint_replays()
    assert len(listing) == 10
    listed_pairs = {(row["variant"], row["seed"]) for row in listing}
    assert listed_pairs == set(EXPECTED_PARTIAL_EPISODES)

    for variant, seed in EXPECTED_PARTIAL_EPISODES:
        rep = load_v16_checkpoint_replay(variant=variant, seed=seed)
        assert rep["provenance_badge"] == "v16-real-gemini-replay"
        assert rep["gate_b_disclosure"] == GATE_B_DISCLOSURE
        assert rep["replay_verified"] is True
        assert rep["done"] is True
        assert rep["tier"] == "hard"
        assert rep["seed"] == seed
        assert rep["variant"] == variant
        assert len(rep["floorplan"]["desks"]) == 40
        assert len(rep["days"]) == rep["final_day"]
        assert len(rep["posterior_trace"]) == rep["final_day"]

        xray = rep["xray"]
        assert set(EXPECTED_BIASES).issubset(set(xray["biases"].keys()))
        for b in EXPECTED_BIASES:
            assert b in xray
            row = xray["biases"][b]
            assert set(row.keys()) == {
                "count",
                "active_in_variant",
                "sample_events",
                "investigator_distraction_calls",
            }
            assert row["investigator_distraction_calls"] >= 0
            for ev in row["sample_events"]:
                assert {"day", "bias", "speaker", "target_suspect", "channel", "excerpt"}.issubset(ev.keys())

        assert xray["solver_comparison"]["bit_exact_immunity"] is True
        assert abs(xray["solver_comparison"]["score_delta"]) <= 1e-9

        if variant == "v5_full9_cocktail":
            assert all(xray["biases"][b]["active_in_variant"] is True for b in EXPECTED_BIASES)
            assert all(xray["biases"][b]["count"] >= 1 for b in EXPECTED_BIASES)
            assert len(rep["rumor_bubbles"]) >= 15
            assert len(rep["messages_read_by_gemini"]) >= 1
            assert len(rep["interviews_by_gemini"]) >= 10
            focal = xray["focal_rumor_suspects"]
            assert focal["primary_suspect"] is not None
            assert focal["secondary_suspect"] is not None
            assert focal["disjoint_from_decoy"] is True
        elif variant == "v0_v14_control":
            assert all(xray["biases"][b]["count"] == 0 for b in EXPECTED_BIASES)
            assert xray["focal_rumor_suspects"]["primary_suspect"] is None


def test_zero_hidden_init_calls_and_zero_secret_or_bias_leak_before_done() -> None:
    sess_a = LivingOfficeSession(tier="medium", seed=3005, variant="v5_full9_cocktail")
    sess_b = LivingOfficeSession(tier="medium", seed=3005, variant="v5_full9_cocktail")
    assert len(sess_a.env.history) == 0
    assert sess_a.done is False

    alt_mole = next(
        eid
        for eid in sess_b.env._ids
        if eid != sess_b.env._world.mole and eid != sess_b.env._world.decoy
    )
    sess_b.env._world.mole = alt_mole
    assert sess_a.state_dict() == sess_b.state_dict()

    with pytest.raises(ValueError):
        sess_a.bias_xray_dict()

    sess_a.call_tool("advance_day", {})
    sess_b.call_tool("advance_day", {})
    sess_a.call_tool("search_messages", {"query": "doc", "day_from": 1, "day_to": 1})
    sess_b.call_tool("search_messages", {"query": "doc", "day_from": 1, "day_to": 1})

    state_a = sess_a.state_dict()
    state_b = sess_b.state_dict()
    assert state_a["floorplan"] == state_b["floorplan"]
    assert state_a["social_feed"] == state_b["social_feed"]
    assert state_a["xray"] is None
    assert state_a["verdict"] is None

    dept_names = [z["name"] for z in state_a["floorplan"]["departments"]]
    assert dept_names == [
        "Engineering",
        "Finance",
        "Sales",
        "Legal",
        "Research",
        "Security Console",
    ]
    desks = state_a["floorplan"]["desks"]
    assert len(desks) == 20
    coords = {(d["grid_x"], d["grid_y"]) for d in desks}
    assert len(coords) == 20
    for d in desks:
        assert {"id", "name", "dept", "role", "grid_x", "grid_y", "status", "bubble_preview"}.issubset(d.keys())
        for forbidden in ("mole", "true_mole", "decoy", "bias", "primary_suspect", "secondary_suspect"):
            assert forbidden not in d

    serialized_public = json.dumps(
        {"floorplan": state_a["floorplan"], "social_feed": state_a["social_feed"]}
    ).lower()
    for b in EXPECTED_BIASES:
        assert b not in serialized_public
    for forbidden_key in ("true_mole", "primary_suspect", "secondary_suspect", "target_suspect"):
        assert forbidden_key not in serialized_public


def test_human_play_and_auto_investigators_unlock_9_bias_xray() -> None:
    opponents = list_mole_opponents()
    assert "default_v0" in opponents
    assert "frontier_synthesis_v14" in opponents

    sess = LivingOfficeSession(
        tier="medium",
        seed=3010,
        variant="v5_full9_cocktail",
        mole_opponent="frontier_synthesis_v14",
    )
    r_emp = sess.call_tool("list_employees", {})
    assert r_emp["ok"] is True
    r_iv = sess.call_tool("interview", {"employee": "e00", "topic": "workload"})
    assert r_iv["ok"] is True
    assert any(item["kind"] == "interview" for item in r_iv["state"]["social_feed"])

    step_gem = sess.step_auto_investigator("gemini_proxy")
    assert step_gem["policy"] == "gemini_proxy"
    assert step_gem["end_day"] >= 2 or step_gem["done"] is True

    if not sess.done:
        step_sol = sess.step_auto_investigator("solver")
        assert step_sol["policy"] == "solver"
        assert len(step_sol["steps_executed"]) >= 1

    if not sess.done:
        sess.call_tool("accuse", {"employee": "e00"})
    assert sess.done is True

    final_state = sess.state_dict()
    assert final_state["xray"] is not None
    assert json.loads(json.dumps(final_state, allow_nan=False))["done"] is True
    xray = sess.bias_xray_dict()
    assert set(EXPECTED_BIASES) == set(xray["biases"].keys())
    assert xray["solver_comparison"]["bit_exact_immunity"] is True

    solver_sess = LivingOfficeSession(tier="medium", seed=3020, variant="v5_full9_cocktail")
    while not solver_sess.done:
        step_out = solver_sess.step_auto_investigator("solver")
        assert step_out["end_day"] > step_out["start_day"] or step_out["done"] is True
    assert solver_sess.state_dict()["score"] == solver_sess.bias_xray_dict()["solver_comparison"]["solver_score"]

    gullible_sess = LivingOfficeSession(tier="medium", seed=3020, variant="v5_full9_cocktail")
    while not gullible_sess.done:
        gullible_sess.step_auto_investigator("bias_gullible")
    g_xray = gullible_sess.bias_xray_dict()
    assert g_xray["total_distraction_calls"] >= 1
    focal_pair = {
        g_xray["focal_rumor_suspects"]["primary_suspect"],
        g_xray["focal_rumor_suspects"]["secondary_suspect"],
    }
    assert gullible_sess.env._accused in focal_pair

    assert len(json.dumps(list_living_office_variants(), allow_nan=False)) > 20
    assert len(json.dumps(list_v16_checkpoint_replays(), allow_nan=False)) > 20
    assert len(json.dumps(load_v16_checkpoint_replay("v5_full9_cocktail", 30), allow_nan=False)) > 100


def test_zero_comments_and_zero_em_en_dashes() -> None:
    root = Path(__file__).resolve().parent.parent
    targets = (
        root / "canary" / "arena" / "living_office.py",
        root / "tests" / "test_arena_living_office.py",
    )
    hash_char = chr(35)
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)

    for path in targets:
        src = path.read_text(encoding="utf-8")
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        comment_tokens = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert len(comment_tokens) == 0, f"comment token found in {path}"
        assert not any(line.lstrip().startswith(hash_char) for line in src.splitlines())
        assert hash_char not in src, f"hash char found in {path}"
        assert em_dash not in src, f"em dash found in {path}"
        assert en_dash not in src, f"en dash found in {path}"
