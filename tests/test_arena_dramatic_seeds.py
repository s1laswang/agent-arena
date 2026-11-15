from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

from canary.analysis.gap import load_runs

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "build_arena_dramatic_seeds.py"
JSON_PATH = ROOT / "docs" / "arena" / "data" / "dramatic_seeds.json"
JS_PATH = ROOT / "docs" / "arena" / "data" / "dramatic_seeds.js"
MD_PATH = ROOT / "docs" / "arena" / "DRAMATIC_SEEDS_3MIN.md"
TEST_PATH = Path(__file__).resolve()

VERIFY_ARENA_POST_END_CONTAINER_KEYS = frozenset(
    {
        "reveal",
        "verdict",
        "final",
        "outcome",
        "terminal",
        "post_game",
        "post_end",
        "case_closed",
        "sealed",
        "sealed_reveal",
        "end_reveal",
        "commitment",
    }
)


def _load_builder_module() -> Any:
    spec = importlib.util.spec_from_file_location("build_arena_dramatic_seeds", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def builder_mod() -> Any:
    return _load_builder_module()


@pytest.fixture(scope="module")
def disk_payload() -> dict[str, Any]:
    return json.loads(JSON_PATH.read_text(encoding="utf-8"))


def test_dramatic_seeds_check_and_roundtrip_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    builder_mod: Any,
    disk_payload: dict[str, Any],
) -> None:
    rc_check = builder_mod.main(["--check", "--root", str(ROOT)])
    assert rc_check == 0

    monkeypatch.setattr(
        builder_mod,
        "build_dramatic_seeds_payload",
        lambda _root=ROOT: copy.deepcopy(disk_payload),
    )

    tmp_json = tmp_path / "dramatic_seeds.json"
    tmp_js = tmp_path / "dramatic_seeds.js"
    rc_write = builder_mod.main(
        [
            "--write",
            "--root",
            str(ROOT),
            "--json-out",
            str(tmp_json),
            "--js-out",
            str(tmp_js),
        ]
    )
    assert rc_write == 0
    assert tmp_json.read_text(encoding="utf-8") == JSON_PATH.read_text(encoding="utf-8")
    assert tmp_js.read_text(encoding="utf-8") == JS_PATH.read_text(encoding="utf-8")
    assert len(JSON_PATH.read_bytes()) < 100_000

    rc_tmp_check = builder_mod.main(
        [
            "--check",
            "--root",
            str(ROOT),
            "--json-out",
            str(tmp_json),
            "--js-out",
            str(tmp_js),
        ]
    )
    assert rc_tmp_check == 0

    tampered = json.loads(tmp_json.read_text(encoding="utf-8"))
    tampered["cards"][0]["title"] = "Tampered Title"
    tmp_json.write_text(json.dumps(tampered, indent=2) + "\n", encoding="utf-8")
    rc_drift = builder_mod.main(
        [
            "--check",
            "--root",
            str(ROOT),
            "--json-out",
            str(tmp_json),
            "--js-out",
            str(tmp_js),
        ]
    )
    assert rc_drift == 1


def test_js_global_contract_and_schema(disk_payload: dict[str, Any]) -> None:
    js_text = JS_PATH.read_text(encoding="utf-8")
    prefix = "globalThis.CANARY_DRAMATIC_SEEDS = "
    assert js_text.startswith(prefix)
    assert js_text.endswith(";\n")
    js_payload = json.loads(js_text[len(prefix) : -2])
    assert js_payload == disk_payload

    assert disk_payload["schema_version"] == "canary_arena_dramatic_seeds_v1"
    assert disk_payload["rules_version"] == "v1.4"
    assert disk_payload["source_pool"] == "data/runs/committed/v1.4"
    assert disk_payload["live_api_calls"] == 0
    assert disk_payload["allowed_public_dev_seed_range"] == [0, 29]
    assert disk_payload["default_duel_seeds"] == [6, 26]
    assert disk_payload["default_seeds"] == [6, 26]

    rv = disk_payload["replay_verification"]
    assert rv["episodes_verified"] == 410
    assert rv["episode_mismatches"] == 0
    assert rv["step_mismatches"] == 0
    assert rv["compat_commit"] == "1bc3e281"

    cards = disk_payload["cards"]
    assert len(cards) == 13
    assert disk_payload["case_order"] == [c["case_id"] for c in cards]
    assert cards[0]["case_id"] == "hard:6"
    assert cards[1]["case_id"] == "hard:26"
    assert cards[0]["is_default_duel"] is True
    assert cards[1]["is_default_duel"] is True
    assert all(c["is_default_duel"] is False for c in cards[2:])

    hard_cards = [c for c in cards if c["tier"] == "hard"]
    med_cards = [c for c in cards if c["tier"] == "medium"]
    assert len(hard_cards) == 10
    assert len(med_cards) == 3

    for card in cards:
        seed = card["seed"]
        assert isinstance(seed, int) and not isinstance(seed, bool)
        assert 0 <= seed <= 29


def test_pre_end_zero_leakage_and_sealed_reveal_container(
    builder_mod: Any,
    disk_payload: dict[str, Any],
) -> None:
    assert builder_mod.POST_END_CONTAINER_KEY == "sealed_reveal"
    assert builder_mod.POST_END_CONTAINER_KEY in VERIFY_ARENA_POST_END_CONTAINER_KEYS
    assert "sealed_dossier" not in VERIFY_ARENA_POST_END_CONTAINER_KEYS

    for card in disk_payload["cards"]:
        assert "sealed_dossier" not in card
        assert "sealed_reveal" in card
        reveal = card["sealed_reveal"]
        assert reveal["sealed"] is True
        assert reveal["done"] is True
        assert reveal["episode_over"] is True
        assert reveal["unlock_condition"] == "humanDone === true"
        builder_mod._assert_pre_end_card_safe(card)

    sample = copy.deepcopy(disk_payload["cards"][1])

    leaked_mole = copy.deepcopy(sample)
    leaked_mole["true_mole"] = "e08"
    with pytest.raises(ValueError, match="forbidden truth key"):
        builder_mod._assert_pre_end_card_safe(leaked_mole)

    leaked_old_container = copy.deepcopy(sample)
    leaked_old_container["sealed_dossier"] = {"true_mole": "e08"}
    with pytest.raises(ValueError, match="sealed_dossier"):
        builder_mod._assert_pre_end_card_safe(leaked_old_container)

    leaked_emp_text = copy.deepcopy(sample)
    leaked_emp_text["tagline"] = "Suspect e08 leaks overnight"
    with pytest.raises(ValueError, match="employee id spoiler"):
        builder_mod._assert_pre_end_card_safe(leaked_emp_text)

    for bad_seed in (30, 800000, 900000, -1, True):
        bad_seed_card = copy.deepcopy(sample)
        bad_seed_card["seed"] = bad_seed
        with pytest.raises(ValueError, match="outside public dev range"):
            builder_mod._assert_pre_end_card_safe(bad_seed_card)

    unsealed_reveal = copy.deepcopy(sample)
    unsealed_reveal["sealed_reveal"]["done"] = False
    with pytest.raises(ValueError, match="missing sealed_reveal"):
        builder_mod._assert_pre_end_card_safe(unsealed_reveal)


def test_fresh_env_forensic_spot_replays(
    monkeypatch: pytest.MonkeyPatch,
    builder_mod: Any,
    disk_payload: dict[str, Any],
) -> None:
    monkeypatch.setenv("CANARY_ALLOW_DEV", "1")
    v14_dir = ROOT / "data" / "runs" / "committed" / "v1.4"
    target_keys = {
        ("opencode:google/gemini-4-carbon", "hard", 6),
        ("solver", "hard", 6),
        ("opencode:google/gemini-4-carbon", "hard", 26),
        ("solver", "hard", 26),
        ("opencode:google/gemini-4-carbon", "hard", 4),
        ("solver", "hard", 4),
        ("opencode:google/gemini-4-carbon", "medium", 20),
        ("solver", "medium", 20),
    }
    found: dict[tuple[str, str, int], dict[str, Any]] = {}
    for ep in load_runs(v14_dir):
        key = (str(ep.get("agent") or ""), str(ep["tier"]), int(ep["seed"]))
        if key in target_keys:
            env, st = builder_mod.replay_and_verify_episode(ep)
            assert st["step_mismatches"] == 0
            found[key] = {"ep": ep, "mole": env._world.mole}

    assert set(found) == target_keys
    by_case = {c["case_id"]: c["sealed_reveal"] for c in disk_payload["cards"]}

    r6 = by_case["hard:6"]
    assert r6["true_mole"] == "e34" == found[("solver", "hard", 6)]["mole"]
    assert r6["gemini_opencode"]["score"] == pytest.approx(0.73)
    assert r6["gemini_opencode"]["final_day"] == 6
    assert r6["gemini_opencode"]["canaries_planted"] == 7
    assert r6["gemini_opencode"]["interviews"] == 25
    assert r6["gemini_opencode"]["tool_calls"] == 57
    assert r6["solver"]["score"] == pytest.approx(0.71)
    assert r6["solver"]["final_day"] == 6

    r26 = by_case["hard:26"]
    assert r26["true_mole"] == "e08" == found[("solver", "hard", 26)]["mole"]
    assert r26["gemini_opencode"]["score"] == pytest.approx(-1.0)
    assert r26["gemini_opencode"]["accused"] == "e04"
    assert r26["gemini_opencode"]["canaries_days_1_to_3"] == 0
    assert r26["gemini_opencode"]["interviews"] == 43
    flips_26 = r26["gemini_opencode"]["fingerprint_flips"]
    assert any(
        f["doc_id"] == "c6-2"
        and f["true_variant"] == "S3"
        and f["shown_variant"] == "S1"
        and f["surfaced_day"] == 10
        for f in flips_26
    )
    assert r26["solver"]["score"] == pytest.approx(0.69)
    assert r26["solver"]["final_day"] == 7

    r4 = by_case["hard:4"]
    assert r4["gemini_opencode"]["score"] == pytest.approx(0.4)
    assert r4["gemini_opencode"]["final_day"] == 16
    assert r4["gemini_opencode"]["interviews"] == 84
    assert r4["gemini_opencode"]["decisive_earlier"]["day"] == 14
    assert r4["solver"]["score"] == pytest.approx(0.73)
    assert r4["solver"]["final_day"] == 5

    rm20 = by_case["medium:20"]
    assert rm20["gemini_opencode"]["score"] == pytest.approx(0.8)
    assert rm20["gemini_opencode"]["final_day"] == 6
    assert rm20["solver"]["score"] == pytest.approx(0.0)
    assert rm20["solver"]["accused"] is None
    assert rm20["solver"]["final_day"] == 14

    hl = disk_payload["headline_v14"]
    oc_h = hl["primary_hard_opencode_gemini_4_carbon"]
    assert oc_h["luck_adjusted_ratio_pct"] == 72
    assert oc_h["luck_adjusted_ratio_ci95_pct"] == [52, 91]
    assert oc_h["raw_ratio_pct"] == 65
    assert oc_h["raw_ratio_ci95_pct"] == [24, 98]
    assert hl["lock_provenance"]["classification"] == "post_hoc_lock"
    assert hl["lock_provenance"]["lock_commit"] == "671ed96"
    assert hl["lock_provenance"]["episodes_commit"] == "8fd4dec"
    assert hl["lock_provenance"]["lock_delay_seconds"] == 28
    assert hl["living_office_gate_b_disclosure"]["passed_gate_b"] is False
    assert hl["living_office_gate_b_disclosure"]["mode_4_enabled_by_default"] is False


def test_3min_presenter_script_and_owned_files_hygiene(disk_payload: dict[str, Any]) -> None:
    md_text = MD_PATH.read_text(encoding="utf-8")
    required_snippets = (
        "0:00-1:15",
        "1:15-1:50",
        "1:50-2:25",
        "2:25-3:00",
        "Duel vs Gemini",
        "Beat the Solver",
        "Be the Mole",
        "Living Office",
        "72% [52%, 91%]",
        "65% [24%, 98%]",
        "671ed96",
        "8fd4dec",
        "post-hoc lock",
        "V1.6 PREVIEW - OFF BY DEFAULT",
        "did NOT pass Gate B",
        "sealed_reveal",
        "globalThis.CANARY_DRAMATIC_SEEDS",
    )
    for snippet in required_snippets:
        assert snippet in md_text, f"missing {snippet!r} in DRAMATIC_SEEDS_3MIN.md"

    for case_id in disk_payload["case_order"]:
        assert f"`{case_id}`" in md_text

    forbidden_secret_literals = (
        "CANARY_WORLD" + "_SECRET",
        "CANARY_LEDGER" + "_TOKEN",
        "data/worlds/judge/" + "SALT",
    )
    owned_files = (SCRIPT_PATH, JSON_PATH, JS_PATH, MD_PATH, TEST_PATH)
    hash_char = chr(35)
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)

    for fp in owned_files:
        assert fp.is_file(), f"missing owned file {fp}"
        txt = fp.read_text(encoding="utf-8")
        assert txt.isascii(), f"non-ASCII character in {fp}"
        assert em_dash not in txt and en_dash not in txt, f"em/en dash in {fp}"
        for secret_lit in forbidden_secret_literals:
            assert secret_lit not in txt, f"forbidden literal {secret_lit} in {fp}"
        if fp.suffix == ".py":
            assert hash_char not in txt, f"hash comment character found in {fp}"
