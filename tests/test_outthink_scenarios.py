from __future__ import annotations

import ast
import io
import json
import tokenize
from collections import defaultdict
from pathlib import Path

import pytest

from canary.gemini.ladder_report import load_ladder, reference_episodes
from canary.gemini.outthink_scenarios import (
    ANNOTATIONS_JSON,
    DEFAULT_JSON_OUT,
    HIGHLIGHT_TAGS,
    LADDER_EPISODES_GZ,
    LADDER_LEVELS,
    MAX_JSON_BYTES,
    PLAYABLE_12_PAIRS,
    ROOT,
    build_scenarios,
    load_playable_pairs,
    main,
    render_json_text,
    validate_scenarios,
)
from canary.world import HELDOUT_SEEDS, JUDGE_SEEDS


@pytest.fixture(scope="module")
def scenarios_doc() -> dict:
    return json.loads(DEFAULT_JSON_OUT.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def annotations_doc() -> dict:
    return json.loads(ANNOTATIONS_JSON.read_text(encoding="utf-8"))


def test_json_file_exists_and_under_size_budget() -> None:
    assert DEFAULT_JSON_OUT.is_file()
    raw_bytes = DEFAULT_JSON_OUT.read_bytes()
    assert 10_000 < len(raw_bytes) < MAX_JSON_BYTES


def test_top_level_schema_and_git_sha(scenarios_doc: dict, annotations_doc: dict) -> None:
    assert set(scenarios_doc.keys()) == {
        "generated_from_git_sha",
        "summary",
        "scenarios",
        "showcase_ranking",
    }
    sha = scenarios_doc["generated_from_git_sha"]
    assert isinstance(sha, str) and len(sha) == 40
    assert all(ch in "0123456789abcdef" for ch in sha)
    assert sha == annotations_doc["generated_from_git_sha"]


def test_summary_exact_counts_and_fields(scenarios_doc: dict, annotations_doc: dict) -> None:
    summary = scenarios_doc["summary"]
    for req in (
        "scenarios_count",
        "tiers",
        "total_episodes",
        "models",
        "levels",
        "best_showcase_scenarios",
    ):
        assert req in summary
    assert summary["scenarios_count"] == 62
    assert summary["total_episodes"] == 587
    assert summary["ladder_episodes"] == 550
    assert summary["tiers"] == ["medium", "hard"]
    assert summary["levels"] == list(LADDER_LEVELS)
    assert summary["models"] == annotations_doc["summary"]["models"]
    best = summary["best_showcase_scenarios"]
    assert isinstance(best, list) and len(best) == 12
    assert best == scenarios_doc["showcase_ranking"][:12]


def test_all_62_scenarios_reconcile_with_annotations_and_solver(
    scenarios_doc: dict,
    annotations_doc: dict,
) -> None:
    scenarios = scenarios_doc["scenarios"]
    assert len(scenarios) == 62
    ann_eps = annotations_doc["episodes"]
    by_scen = annotations_doc["by_scenario"]

    pairs = {(s["tier"], int(s["seed"])) for s in scenarios.values()}
    assert len(pairs) == 62
    for _, seed_i in pairs:
        assert seed_i not in JUDGE_SEEDS
        assert seed_i not in HELDOUT_SEEDS

    ref_eps = reference_episodes(pairs, agents=("solver",))
    ref_scores = {(str(e["tier"]), int(e["seed"])): float(e["score"]) for e in ref_eps}
    assert len(ref_scores) == 62

    ep_total = 0
    for sk, sc in scenarios.items():
        tier = sc["tier"]
        seed = sc["seed"]
        assert sk == f"{tier}:{seed}"
        assert sc["key"] == sk
        raw_sk = f"{tier}/{seed}"
        assert raw_sk in by_scen

        raw_eps = [
            ann_eps[ek]
            for lv_map in by_scen[raw_sk].values()
            for ek in lv_map.values()
        ]
        assert sc["episode_count"] == len(raw_eps)
        ep_total += sc["episode_count"]

        assert abs(sc["solver_score"] - ref_scores[(tier, seed)]) < 1e-6
        assert set(sc["models_present"]) == {e["model"] for e in raw_eps}

        by_lv: dict[str, list[dict]] = defaultdict(list)
        for ep in raw_eps:
            if ep["level"] in LADDER_LEVELS:
                by_lv[ep["level"]].append(ep)

        expected_lvs = [lv for lv in LADDER_LEVELS if lv in by_lv]
        assert list(sc["accuracy_by_level"].keys()) == expected_lvs
        assert list(sc["mean_score_by_level"].keys()) == expected_lvs
        assert list(sc["mean_regret_by_level"].keys()) == expected_lvs

        for lv in expected_lvs:
            lv_eps = by_lv[lv]
            exp_acc = sum(1.0 if e["correct"] else 0.0 for e in lv_eps) / len(lv_eps)
            exp_score = sum(float(e["score"]) for e in lv_eps) / len(lv_eps)
            exp_reg = sum(float(e["regret_total"]) for e in lv_eps) / len(lv_eps)
            assert 0.0 <= sc["accuracy_by_level"][lv] <= 1.0
            assert abs(sc["accuracy_by_level"][lv] - exp_acc) < 1e-5
            assert abs(sc["mean_score_by_level"][lv] - exp_score) < 1e-5
            assert abs(sc["mean_regret_by_level"][lv] - exp_reg) < 1e-5

        vals = list(sc["mean_score_by_level"].values())
        exp_spread = round(max(vals) - min(vals), 6) if len(vals) >= 2 else 0.0
        assert abs(sc["ladder_spread"] - exp_spread) < 1e-6

    assert ep_total == 587


def test_ladder_550_episodes_covered(scenarios_doc: dict) -> None:
    ladder_eps = load_ladder(LADDER_EPISODES_GZ)
    assert len(ladder_eps) == 550
    scenarios = scenarios_doc["scenarios"]
    for ep in ladder_eps:
        cell = ep["_cell"]
        sk = f"{cell['tier']}:{cell['seed']}"
        assert sk in scenarios
        assert cell["model"] in scenarios[sk]["models_present"]
        assert cell["level"] in scenarios[sk]["mean_score_by_level"]


def test_dominant_failure_tags_reconcile(scenarios_doc: dict, annotations_doc: dict) -> None:
    scenarios = scenarios_doc["scenarios"]
    expected_totals = annotations_doc["summary"]["highlighted_tag_episode_counts"]
    for tg in HIGHLIGHT_TAGS:
        total = sum(sc["dominant_failure_tags"][tg] for sc in scenarios.values())
        assert total == expected_totals[tg]
    for sc in scenarios.values():
        assert tuple(sc["dominant_failure_tags"].keys()) == HIGHLIGHT_TAGS
        for cnt in sc["dominant_failure_tags"].values():
            assert 0 <= cnt <= sc["episode_count"]


def test_anchor_runs_match_annotations_exact(scenarios_doc: dict, annotations_doc: dict) -> None:
    ann_eps = annotations_doc["episodes"]
    by_run_id = {ep["run_id"]: ep for ep in ann_eps.values() if ep.get("run_id")}
    for sk, sc in scenarios_doc["scenarios"].items():
        anchors = sc["anchor_runs"]
        assert 1 <= len(anchors) <= 3
        seen_ids: set[str] = set()
        for ar in anchors:
            rid = ar["run_id"]
            assert isinstance(rid, str) and rid
            assert rid not in seen_ids
            seen_ids.add(rid)
            assert rid in by_run_id
            ref = by_run_id[rid]
            assert ref["tier"] == sc["tier"]
            assert ref["seed"] == sc["seed"]
            for field in ("key", "model", "level", "score", "correct", "primary_failure_tag"):
                assert ar[field] == ref[field], f"{sk} {rid} mismatch on {field}"


def test_showcase_ranking_and_decision_contrast(scenarios_doc: dict) -> None:
    ranking = scenarios_doc["showcase_ranking"]
    scenarios = scenarios_doc["scenarios"]
    assert len(ranking) == 62
    assert set(ranking) == set(scenarios.keys())

    for idx, sk in enumerate(ranking, start=1):
        assert scenarios[sk]["showcase_rank"] == idx

    contrast_flags = [scenarios[sk]["decision_contrast"] for sk in ranking]
    first_false = contrast_flags.index(False)
    assert first_false >= 15
    assert all(not flag for flag in contrast_flags[first_false:])

    top_three = ranking[:3]
    for sk in top_three:
        sc = scenarios[sk]
        assert sc["decision_contrast"] is True
        assert sc["ladder_spread"] >= 1.5
        low_vals = [sc["mean_score_by_level"][lv] for lv in ("minimal", "low") if lv in sc["mean_score_by_level"]]
        high_vals = [sc["mean_score_by_level"][lv] for lv in ("high", "xhigh") if lv in sc["mean_score_by_level"]]
        assert min(low_vals) <= -1.0
        assert max(high_vals) > 0.3


def test_playable_12_flag_default_and_custom_json(scenarios_doc: dict, tmp_path: Path) -> None:
    scenarios = scenarios_doc["scenarios"]
    flagged = {(sc["tier"], sc["seed"]) for sc in scenarios.values() if sc["in_playable_12"]}
    assert flagged == set(PLAYABLE_12_PAIRS)
    assert len(flagged) == 11
    for sc in scenarios.values():
        assert isinstance(sc["in_playable_12"], bool)

    custom_playable = tmp_path / "out_think_gemini.json"
    custom_playable.write_text(
        json.dumps({"cases": [{"tier": "medium", "seed": 0}, {"tier": "hard", "seed": 8}]}),
        encoding="utf-8",
    )
    loaded_pairs = load_playable_pairs(custom_playable)
    assert loaded_pairs == {("medium", 0), ("hard", 8)}
    custom_doc = build_scenarios(playable_json_path=custom_playable)
    custom_flagged = {
        sk for sk, sc in custom_doc["scenarios"].items() if sc["in_playable_12"]
    }
    assert custom_flagged == {"medium:0", "hard:8"}


def test_cli_check_and_roundtrip(tmp_path: Path, annotations_doc: dict) -> None:
    assert main(["--check"]) == 0

    out_fp = tmp_path / "scenarios_out.json"
    assert main(["--json-out", str(out_fp)]) == 0
    assert out_fp.is_file()
    assert main(["--json-out", str(out_fp), "--check"]) == 0

    rebuilt = json.loads(out_fp.read_text(encoding="utf-8"))
    assert validate_scenarios(rebuilt, annotations_doc=annotations_doc) == []
    assert render_json_text(rebuilt) == DEFAULT_JSON_OUT.read_text(encoding="utf-8")

    tampered = tmp_path / "tampered.json"
    tampered.write_text("{}", encoding="utf-8")
    assert main(["--json-out", str(tampered), "--check"]) == 1


def test_zero_comments_zero_unicode_dashes_zero_live_imports() -> None:
    py_files = (
        ROOT / "canary" / "gemini" / "outthink_scenarios.py",
        ROOT / "tests" / "test_outthink_scenarios.py",
    )
    all_files = (*py_files, DEFAULT_JSON_OUT)
    hash_char = chr(35)
    dash_chars = tuple(chr(c) for c in (0x2012, 0x2013, 0x2014, 0x2015))
    dash_escapes = tuple("\\u" + f"{c:04x}" for c in (0x2012, 0x2013, 0x2014, 0x2015))

    for fp in py_files:
        src = fp.read_text(encoding="utf-8")
        assert hash_char not in src, f"comment or hash char found in {fp}"
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        assert not [t for t in tokens if t.type == tokenize.COMMENT]

    for fp in all_files:
        txt = fp.read_text(encoding="utf-8")
        for dch in dash_chars:
            assert dch not in txt, f"unicode dash in {fp}"
        low = txt.lower()
        for desc in dash_escapes:
            assert desc not in low, f"escaped unicode dash in {fp}"

    mod_tree = ast.parse((ROOT / "canary" / "gemini" / "outthink_scenarios.py").read_text(encoding="utf-8"))
    forbidden_modules = {"requests", "httpx", "urllib", "http", "socket", "google", "canary.gemini.sdk"}
    for node in ast.walk(mod_tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                assert top not in forbidden_modules and alias.name not in forbidden_modules
        elif isinstance(node, ast.ImportFrom) and node.module:
            top = node.module.split(".")[0]
            assert top not in forbidden_modules and node.module not in forbidden_modules
