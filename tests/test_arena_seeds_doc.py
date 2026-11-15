from __future__ import annotations

import io
import json
import re
import tokenize
from pathlib import Path

from game.canary_game import SEED_MAX, SEED_MIN, TIER, solver_result

ROOT = Path(__file__).resolve().parents[1]
DOC_PATH = ROOT / "docs" / "arena" / "SEEDS.md"
TEST_PATH = Path(__file__).resolve()


def _extract_json_blocks(markdown_text: str) -> list[dict]:
    blocks = re.findall(r"```json\s*\n(.*?)\n```", markdown_text, flags=re.DOTALL)
    return [json.loads(raw) for raw in blocks]


def test_arena_seeds_doc_exists_and_hygiene() -> None:
    assert DOC_PATH.is_file(), f"missing {DOC_PATH}"
    text = DOC_PATH.read_text(encoding="utf-8")
    assert all(ord(ch) < 128 for ch in text), "SEEDS.md must be pure ASCII"
    assert "\u2014" not in text
    assert "\u2013" not in text
    assert "Co-Authored-By" not in text


def test_arena_seeds_test_file_has_zero_comments_and_ascii() -> None:
    src = TEST_PATH.read_text(encoding="utf-8")
    assert all(ord(ch) < 128 for ch in src)
    tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
    comment_tokens = [tok for tok in tokens if tok.type == tokenize.COMMENT]
    assert comment_tokens == []


def test_arena_seeds_json_manifest_and_numbers() -> None:
    text = DOC_PATH.read_text(encoding="utf-8")
    blocks = _extract_json_blocks(text)
    assert len(blocks) == 1
    manifest = blocks[0]

    assert manifest["rules_version"] == "v1.4"
    guards = manifest["hidden_truth_guards"]
    assert guards["duel_day_clamp"] == "day <= humanDay"
    assert guards["early_accuse_mask"] == "[SEALED]"
    assert guards["reveal_condition"] == "humanDone === true"

    m1 = manifest["mode_1_solo_investigator"]
    assert m1["tier"] == TIER == "medium"
    assert m1["allowed_seed_range"] == [SEED_MIN, SEED_MAX] == [3000, 9999]
    assert m1["default_seed"] == 3000
    assert m1["tier_params"] == {
        "n_employees": 20,
        "n_days": 14,
        "tool_call_cap": 300,
        "actions_per_day": 8,
    }

    s3000 = solver_result(3000)
    bench = m1["default_seed_solver_benchmark"]
    assert bench["seed"] == 3000
    assert bench["score"] == round(s3000["score"], 2) == 0.79
    assert bench["final_day"] == s3000["final_day"] == 6
    assert bench["tool_calls"] == s3000["tool_calls"] == 48
    assert bench["correct"] is True
    assert bench["live_mole_id"] == "[SEALED]"

    m2 = manifest["mode_2_ai_duel"]
    assert m2["panel_schema"] == ["seed", "tier", "agent", "steps", "final"]
    by_seed = {entry["seed"]: entry for entry in m2["headline_seeds"]}
    assert set(by_seed) == {6, 26, 4}

    s6 = by_seed[6]
    assert s6["label"] == "Caught"
    assert s6["solver"] == {
        "score": 0.71,
        "final_day": 6,
        "tool_calls": 52,
        "canaries": 9,
        "interviews": 0,
        "correct": True,
    }
    assert s6["gemini_4_carbon_opencode"] == {
        "score": 0.73,
        "final_day": 6,
        "tool_calls": 57,
        "canaries": 7,
        "interviews": 25,
        "correct": True,
    }
    assert s6["live_accuse_target_while_playing"] == "[SEALED]"
    assert s6["post_game_culprit_when_humanDone"] == "e34"

    s26 = by_seed[26]
    assert s26["label"] == "Fooled"
    assert s26["solver"]["score"] == 0.69
    assert s26["solver"]["final_day"] == 7
    assert s26["solver"]["tool_calls"] == 60
    assert s26["solver"]["canaries"] == 11
    assert s26["gemini_4_carbon_opencode"]["score"] == -1.0
    assert s26["gemini_4_carbon_opencode"]["final_day"] == 10
    assert s26["gemini_4_carbon_opencode"]["tool_calls"] == 91
    assert s26["gemini_4_carbon_opencode"]["canaries_days_1_to_3"] == 0
    assert s26["gemini_4_carbon_opencode"]["interviews"] == 43
    assert s26["gemini_4_carbon_opencode"]["noisy_s1_posterior_drop"] == [0.48, 0.03]
    assert s26["gemini_4_carbon_opencode"]["post_game_accused_innocent"] == "e04"
    assert s26["post_game_culprit_when_humanDone"] == "e08"

    s4 = by_seed[4]
    assert s4["label"] == "Slow Moment"
    assert s4["solver"]["score"] == 0.73
    assert s4["solver"]["final_day"] == 5
    assert s4["solver"]["tool_calls"] == 44
    assert s4["solver"]["canaries"] == 7
    assert s4["gemini_4_carbon_opencode"]["score"] == 0.4
    assert s4["gemini_4_carbon_opencode"]["final_day"] == 16
    assert s4["gemini_4_carbon_opencode"]["tool_calls"] == 155
    assert s4["gemini_4_carbon_opencode"]["interviews"] == 84
    assert s4["gemini_4_carbon_opencode"]["share_of_solver_value"] == 0.55
    assert s4["post_game_culprit_when_humanDone"] == "e11"

    pack = m2["featured_replay_pack"]
    assert pack["hard"] == [1, 11, 15, 18]
    assert pack["medium"] == [0, 12]
    assert pack["tiebreak_heldout_replay_only"] == [800000, 800001, 800002]

    m3 = manifest["mode_3_be_the_mole"]
    assert m3["curated_public_seeds"] == list(range(3000, 3010))
    assert m3["action_contract"] == "onMoleAction({type:'leak'|'hold', doc_id})"
    assert "is_canary" in m3["strip_while_not_episodeDone"]
    assert "canary_variants" in m3["strip_while_not_episodeDone"]

    m4 = manifest["mode_4_living_office"]
    assert m4["enabled_by_default"] is False
    assert m4["badge"] == "v1.6 preview"
    assert "61% -> 108%" in m4["gate_b_note"]


def test_arena_seeds_prose_invariants_present() -> None:
    text = DOC_PATH.read_text(encoding="utf-8")
    for token in (
        "[SEALED]",
        "humanDone",
        "day <= humanDay",
        "AiDuelPanel",
        "onMoleAction({type:'leak'|'hold', doc_id})",
        "is_canary",
        "canary_variants",
        "v1.6 preview",
        "61% -> 108%",
    ):
        assert token in text, f"missing required invariant token: {token}"
