from __future__ import annotations

import io
import json
from pathlib import Path
import tokenize

import pytest

from canary.gemini.provenance import TARGET_MODEL, audit_provenance, scan_file_secrets
from canary.gemini.six_roles_docs import sync_six_roles_docs
from scripts.consolidate_world_text import (
    DEFAULT_REL_OUT,
    SUITE_DIR_NAME,
    consolidate_world_text,
    main,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
COMMIT_SHA = "92543d41ece9f81bdb7ce2232fa84e2604e39598"


@pytest.fixture(autouse=True)
def _hermetic_keyless(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_API_KEY", "")
    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY", "")
    monkeypatch.delenv("GEMINI_GATEWAY_URL", raising=False)
    monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(tmp_path / "ledger.jsonl"))


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _build_synthetic_worldtext_tree(root: Path) -> Path:
    wt_root = root / "results" / "gemini_roles" / "world_text"

    _write_json(
        wt_root / "carbon-v14-synth" / "meta.json",
        {
            "role": "world_text",
            "subrole": "company_personas_chatter",
            "model_id": TARGET_MODEL,
            "commit": COMMIT_SHA,
            "n_worlds": 2,
            "n_personas_generated": 60,
            "n_llm_personas": 60,
            "n_day_messages_generated": 24,
            "gemini_provider_fallbacks": 0,
            "truth_leak_violations": 0,
            "lint_violations": 0,
            "solver_mean_score": 0.70,
            "template_baseline_mean_score": 0.70,
            "solver_accuracy": 1.0,
            "usage": {"calls": 10, "in": 12000, "out": 5000, "thinking": 6000, "cached": 0, "cost_usd": 0.15},
        },
    )
    _write_json(
        wt_root / "carbon-v14-synth" / "samples.json",
        {
            "worlds": [
                {
                    "tier": "medium",
                    "seed": 0,
                    "world_builder": {"n_personas": 20, "n_llm_personas": 20, "llm_ok": True},
                    "solver_verification": {"score": 0.75, "correct": True, "template_baseline_score": 0.75, "score_delta": 0.0},
                },
                {
                    "tier": "hard",
                    "seed": 0,
                    "world_builder": {"n_personas": 40, "n_llm_personas": 40, "llm_ok": True},
                    "solver_verification": {"score": 0.65, "correct": True, "template_baseline_score": 0.65, "score_delta": 0.0},
                },
            ]
        },
    )

    _write_json(
        wt_root / "biased-chatter-synth" / "meta.json",
        {
            "role": "world_text",
            "subrole": "biased_chatter_hard",
            "model_id": TARGET_MODEL,
            "commit": COMMIT_SHA,
            "tier": "hard",
            "seeds": [0, 1],
            "n_messages": 30,
            "n_llm_messages": 30,
            "n_fallback_messages": 0,
            "truth_leak_violations": 0,
            "lint_violations": 0,
            "encoding_scan_violations": 0,
            "usage": {"calls": 6, "in": 15000, "out": 6000, "thinking_tokens": 3000, "cached_tokens": 0, "cost_usd": 0.09},
        },
    )

    _write_json(
        wt_root / "biased-ablation-synth" / "meta.json",
        {
            "role": "world_text",
            "subrole": "biased_chatter_investigator_ablation",
            "model_id": TARGET_MODEL,
            "commit": COMMIT_SHA,
            "tier": "hard",
            "seeds": [0],
            "episode_count": 6,
            "carbon_biased_mean": 0.62,
            "carbon_template_mean": 0.64,
            "solver_biased_mean": 0.66,
            "solver_template_mean": 0.66,
            "obvious_biased_mean": -1.0,
            "usage": {"calls": 180, "in": 5000000, "out": 80000, "thinking_tokens": 70000, "cached_tokens": 4500000, "cost_usd": 2.10},
        },
    )
    _write_json(
        wt_root / "biased-ablation-synth" / "comparison.json",
        {
            "episodes": [
                {"tier": "hard", "seed": 0, "policy": "carbon", "world": "biased", "score": 0.62, "correct": True, "rumor_target_distracted": True, "rumor_target_accused": False, "rumor_target_action_share": 0.05},
                {"tier": "hard", "seed": 0, "policy": "carbon", "world": "template", "score": 0.64, "correct": True, "rumor_target_distracted": False, "rumor_target_accused": False, "rumor_target_action_share": 0.0},
                {"tier": "hard", "seed": 0, "policy": "solver", "world": "biased", "score": 0.66, "correct": True, "rumor_target_distracted": False, "rumor_target_accused": False, "rumor_target_action_share": 0.0},
                {"tier": "hard", "seed": 0, "policy": "solver", "world": "template", "score": 0.66, "correct": True, "rumor_target_distracted": False, "rumor_target_accused": False, "rumor_target_action_share": 0.0},
                {"tier": "hard", "seed": 0, "policy": "obvious_heuristic", "world": "biased", "score": -1.0, "correct": False, "rumor_target_distracted": False, "rumor_target_accused": False, "rumor_target_action_share": 0.0},
                {"tier": "hard", "seed": 0, "policy": "obvious_heuristic", "world": "template", "score": -1.0, "correct": False, "rumor_target_distracted": False, "rumor_target_accused": False, "rumor_target_action_share": 0.0},
            ]
        },
    )

    _write_json(
        wt_root / "interviews-synth" / "meta.json",
        {
            "role": "world_text",
            "subrole": "persona_interviews",
            "model_id": TARGET_MODEL,
            "commit": COMMIT_SHA,
            "count": 16,
            "n_interviews_generated": 16,
            "n_worlds": 2,
            "signal_calibration_accuracy": 1.0,
            "counterfactual_prompt_invariance_rate": 1.0,
            "pairwise_signal_ordering_rate": 1.0,
            "solver_mean_score": 0.68,
            "template_baseline_mean_score": 0.68,
            "truth_leak_violations": 0,
            "prompt_truth_leak_violations": 0,
            "lint_violations": 0,
            "stego_leak_violations": 0,
            "usage": {"calls": 16, "in": 16000, "out": 1200, "thinking": 3200, "cached": 0, "cost_usd": 0.08},
        },
    )
    _write_json(
        wt_root / "interviews-synth" / "solver_parity.json",
        {
            "per_world": [
                {"tier": "medium", "seed": 0, "persona_solver": {"score": 0.72, "correct": True}, "template_solver": {"score": 0.72, "correct": True}, "persona_obvious_heuristic": {"score": -1.0}},
                {"tier": "hard", "seed": 0, "persona_solver": {"score": 0.64, "correct": True}, "template_solver": {"score": 0.64, "correct": True}, "persona_obvious_heuristic": {"score": -1.0}},
            ]
        },
    )

    _write_json(
        wt_root / "events-synth" / "meta.json",
        {
            "role": "world_text",
            "subrole": "dynamic_mid_episode_events",
            "model_id": TARGET_MODEL,
            "commit": COMMIT_SHA,
            "tier": "hard",
            "seeds": [0, 1],
            "days": [4, 9, 15],
            "n_events_generated": 6,
            "truth_leak_violations": 0,
            "lint_violations": 0,
            "stego_leak_violations": 0,
            "solver_parity_ok": True,
            "usage": {"calls": 6, "in": 32000, "out": 2000, "thinking": 3500, "cached": 0, "cost_usd": 0.12},
        },
    )
    _write_json(
        wt_root / "events-synth" / "solver_parity.json",
        {
            "per_seed": [
                {"seed": 0, "live_events_solver": {"score": 0.64, "correct": True}, "baseline_solver": {"score": 0.64, "correct": True}, "live_events_obvious_heuristic": {"score": -1.0}},
                {"seed": 1, "live_events_solver": {"score": 0.69, "correct": True}, "baseline_solver": {"score": 0.69, "correct": True}, "live_events_obvious_heuristic": {"score": -1.0}},
            ]
        },
    )

    _write_json(
        wt_root / "thinking-synth" / "meta.json",
        {
            "role": "world_text",
            "subrole": "thinking_level_calibration",
            "model_id": TARGET_MODEL,
            "commit": COMMIT_SHA,
            "tier": "medium",
            "seeds": [6],
            "n_worlds": 3,
            "solver_parity_ok": True,
            "truth_leak_violations": 0,
            "lint_violations": 0,
            "leak_encoding_violations": 0,
            "fallback_count": 0,
            "levels_summary": {
                "low": {"thinking_tokens": 0, "output_tokens": 2200, "distinct_bigrams": 1100, "solver_mean_score": 0.78, "cost_usd": 0.03},
                "medium": {"thinking_tokens": 1800, "output_tokens": 2100, "distinct_bigrams": 1150, "solver_mean_score": 0.78, "cost_usd": 0.05},
                "high": {"thinking_tokens": 19000, "output_tokens": 2500, "distinct_bigrams": 1700, "solver_mean_score": 0.78, "cost_usd": 0.22},
            },
            "usage": {"calls": 12, "in": 12000, "out": 6800, "thinking": 20800, "cached": 0, "cost_usd": 0.30},
        },
    )

    return root


def test_synthetic_worldtext_suite_consolidation(tmp_path: Path) -> None:
    root = _build_synthetic_worldtext_tree(tmp_path / "ws")
    out_dir = root / DEFAULT_REL_OUT
    _write_json(out_dir / "meta.json", {"stale": True})

    rc = main(["--root", str(root)])
    assert rc == 0
    assert not (out_dir / "meta.json").exists()
    assert (out_dir / "suite.json").is_file()
    assert (out_dir / "summary.md").is_file()

    suite = json.loads((out_dir / "suite.json").read_text(encoding="utf-8"))
    summary_md = (out_dir / "summary.md").read_text(encoding="utf-8")
    assert EM_DASH not in summary_md
    assert EN_DASH not in summary_md

    assert suite["totals"]["verified_folders"] == 6
    assert suite["totals"]["calls"] == 230
    assert suite["leak_and_safety_audit"]["all_clean"] is True
    assert suite["company_personas_suite"]["unique_worlds"] == 2
    assert suite["company_personas_suite"]["unique_personas"] == 60
    assert suite["biased_chatter_suite"]["total_biased_messages"] == 30
    assert suite["biased_chatter_suite"]["unique_ablation_episodes"] == 6
    assert suite["persona_interviews_suite"]["total_interviews"] == 16
    assert suite["dynamic_events_suite"]["total_events_generated"] == 6
    assert suite["thinking_calibration_suite"]["levels"]["high"]["thinking_tokens"] == 19000


def test_committed_worldtext_suite_matches_provenance_keyless() -> None:
    suite = consolidate_world_text(root=REPO_ROOT, write_files=False)
    prov = audit_provenance(REPO_ROOT)
    assert prov["verified"] is True
    assert prov["secret_leaks"] == []

    wt_prov_runs = [
        r for r in prov["runs"]
        if r["verified"] and r["role"] == "world_text"
    ]
    assert suite["totals"]["verified_folders"] == len(wt_prov_runs)
    assert suite["totals"]["verified_folders"] >= 13
    assert suite["totals"]["in"] == sum(int(r["tokens_in"]) for r in wt_prov_runs)
    assert suite["totals"]["out"] == sum(int(r["tokens_out"]) for r in wt_prov_runs)
    assert suite["totals"]["cost_usd"] == pytest.approx(
        sum(float(r["cost_usd"]) for r in wt_prov_runs),
        abs=1e-4,
    )
    assert suite["leak_and_safety_audit"]["all_clean"] is True
    assert suite["company_personas_suite"]["unique_worlds"] >= 24
    assert suite["company_personas_suite"]["unique_personas"] >= 648
    assert suite["biased_chatter_suite"]["total_biased_messages"] >= 70
    assert suite["biased_chatter_suite"]["unique_ablation_episodes"] >= 24
    assert suite["persona_interviews_suite"]["total_interviews"] >= 32
    assert suite["dynamic_events_suite"]["total_events_generated"] >= 33
    assert suite["thinking_calibration_suite"]["total_calibrated_worlds"] >= 6

    suite_dir = REPO_ROOT / DEFAULT_REL_OUT
    assert suite_dir.name == SUITE_DIR_NAME
    if suite_dir.is_dir():
        assert not (suite_dir / "meta.json").exists()
        for fname in ("suite.json", "summary.md"):
            fpath = suite_dir / fname
            assert fpath.is_file()
            raw = fpath.read_text(encoding="utf-8")
            assert EM_DASH not in raw
            assert EN_DASH not in raw
            assert scan_file_secrets(fpath, REPO_ROOT) == []

    check_docs = sync_six_roles_docs(REPO_ROOT, check=True, strict=True)
    assert check_docs["ok"] is True


def test_consolidate_world_text_hygiene() -> None:
    for path in (
        REPO_ROOT / "scripts" / "consolidate_world_text.py",
        REPO_ROOT / "tests" / "test_consolidate_world_text.py",
    ):
        text = path.read_text(encoding="utf-8")
        assert EM_DASH not in text
        assert EN_DASH not in text
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
        comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert comments == [], f"Found comments in {path}: {comments}"
        assert scan_file_secrets(path, REPO_ROOT) == []
