from __future__ import annotations

import ast
import copy
import dataclasses
import io
import json
import sys
import time
import tokenize
from pathlib import Path

from canary import world as canary_world
from canary.env import Env
from canary.eval import run_episode
import scripts.tiebreak_vs_frontier_comparison as cmp_mod
from train.empirical_bayes_policy import EmpiricalBayesParams, EmpiricalBayesPolicy, make_naive_prior_params

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "tiebreak_vs_frontier_comparison.py"
SUMMARY_JSON_PATH = REPO_ROOT / "results" / "tiebreak" / "frontier_comparison" / "comparison_summary.json"
REPORT_MD_PATH = REPO_ROOT / "docs" / "reports" / "tiebreak_vs_frontier.md"
SELF_PATH = Path(__file__).resolve()


def test_source_and_artifacts_hygiene() -> None:
    hash_char = chr(35)
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    forbidden_imports = {"torch", "transformers", "peft", "google"}

    for py_path in (SCRIPT_PATH, SELF_PATH):
        src = py_path.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(py_path))
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
        assert not [t for t in toks if t.type == tokenize.COMMENT]
        assert hash_char not in src
        assert em_dash not in src
        assert en_dash not in src
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] not in forbidden_imports
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in forbidden_imports

    assert "torch" not in sys.modules
    assert "transformers" not in sys.modules

    fc_dir = SUMMARY_JSON_PATH.parent
    assert SUMMARY_JSON_PATH.is_file()
    assert REPORT_MD_PATH.is_file()
    assert not (fc_dir / "summary.json").exists()
    assert not (fc_dir / "table.md").exists()

    for artifact in (SUMMARY_JSON_PATH, REPORT_MD_PATH):
        txt = artifact.read_text(encoding="utf-8")
        assert em_dash not in txt
        assert en_dash not in txt
        assert cmp_mod._has_affirmative_prereg_0_29(txt) == []
        assert "post-hoc locked, not pre-registered" in txt.lower()


def test_committed_json_and_markdown_deterministic_parity() -> None:
    t0 = time.perf_counter()
    summary = json.loads(SUMMARY_JSON_PATH.read_text(encoding="utf-8"))
    rendered_md = cmp_mod.render_comparison_markdown(summary)
    errs = cmp_mod.check_comparison_artifacts(summary, rendered_md, SUMMARY_JSON_PATH, REPORT_MD_PATH)
    elapsed = time.perf_counter() - t0

    assert errs == []
    assert elapsed < 1.0
    assert summary["schema"] == cmp_mod.SCHEMA_ID
    assert summary["tiers_version"] == "v1.4"
    assert summary["dev_eval_seed_range"] == "0..29"
    assert summary["train_seed_range"] == "102000..102779"
    assert summary["heldout_seed_range"] == "800000..800029"
    assert summary["dev_hard_panel"]["protocol_status"] == "post-hoc locked, not pre-registered"
    assert summary["dev_medium_panel"]["protocol_status"] == "post-hoc locked, not pre-registered"

    rat = summary["replay_audit_totals"]
    assert rat["fresh_env_step_replayed_episodes"] == 510
    assert rat["fresh_env_step_verified_episodes"] == 510
    assert rat["fresh_env_mismatches"] == 0
    assert rat["solver_heldout_reference_verified_episodes"] == 90
    assert rat["verda_transcript_belief_replayed_episodes"] == 450
    assert rat["verda_transcript_protocol_verified_episodes"] == 450
    assert rat["total_trajectories_audited"] == 960

    tc = summary["thesis_convergence"]
    ue = tc["under_exploration_canary_deficit"]
    assert ue["gemini_4_carbon_hard_dev_canaries_before_accuse"] < ue["solver_hard_dev_canaries_before_accuse"]
    assert ue["gemini_4_carbon_hard_dev_diagnostic_variants"] < ue["solver_hard_dev_diagnostic_variants"]
    assert ue["qwen15b_v2_off30_canaries_before_accuse"] < ue["solver_hard_dev_canaries_before_accuse"]
    assert ue["qwen15b_v3_4k_pooled_canaries_before_accuse"] < ue["solver_hard_dev_canaries_before_accuse"]
    assert ue["eb_trained_heldout_canaries_before_accuse"] > ue["eb_uncalibrated_heldout_canaries_before_accuse"]

    pc = tc["premature_commitment_below_breakeven"]
    assert pc["solver_hard_dev_top_p_below_breakeven_rate"] == 0.0
    assert pc["gemini_4_carbon_hard_dev_top_p_below_breakeven_rate"] > 0.0
    assert pc["qwen15b_v2_pooled_172_p_accused_below_breakeven_rate"] > 0.90
    assert pc["qwen15b_v3_4k_pooled_p_accused_below_breakeven_rate"] > 0.90
    assert pc["qwen15b_v3_8k_s1_p_accused_below_breakeven_rate"] > 0.90
    assert pc["eb_uncalibrated_hard_dev_top_p_below_breakeven_rate"] > 0.80
    assert pc["eb_trained_hard_dev_top_p_below_breakeven_rate"] == 0.0
    assert pc["eb_uncalibrated_heldout_top_p_below_breakeven_rate"] > 0.50
    assert pc["eb_trained_heldout_top_p_below_breakeven_rate"] == 0.0

    eb_pair = summary["heldout_panel"]["empirical_bayes_paired_n90"]
    assert eb_pair["n"] == 90
    assert eb_pair["mean_delta"] > 0.90
    assert eb_pair["ci95_low"] > 0.80


def test_single_episode_fresh_env_and_belief_replay_unit() -> None:
    gem_eps = cmp_mod._load_valid_episodes(
        REPO_ROOT,
        ("data/runs/committed/v1.4/opencode-gemini-4-carbon/hard/episodes.jsonl",),
        tier_filter="hard",
    )
    rec_gem = cmp_mod.analyze_single_episode(gem_eps[0], verify_with_env=True, world_secret=None)
    assert rec_gem["env_replay_verified"] is True
    assert rec_gem["protocol_consistent"] is True

    tampered_gem = copy.deepcopy(gem_eps[0])
    tampered_gem["score"] = float(tampered_gem["score"]) + 0.25
    rec_bad_gem = cmp_mod.analyze_single_episode(tampered_gem, verify_with_env=True, world_secret=None)
    assert rec_bad_gem["env_replay_verified"] is False
    assert rec_bad_gem["protocol_consistent"] is False

    verda_eps = cmp_mod._load_valid_episodes(
        REPO_ROOT,
        ("data/fr8/verda/h100-3bb7/runs/v3-verda-s0/episodes.jsonl",),
        tier_filter="medium",
    )
    rec_verda = cmp_mod.analyze_single_episode(verda_eps[0], verify_with_env=False, world_secret=None)
    assert rec_verda["env_replay_attempted"] is False
    assert rec_verda["protocol_consistent"] is True

    tampered_verda = copy.deepcopy(verda_eps[0])
    tampered_verda["end_reason"] = "horizon"
    tampered_verda["score"] = 0.5
    rec_bad_verda = cmp_mod.analyze_single_episode(tampered_verda, verify_with_env=False, world_secret=None)
    assert rec_bad_verda["protocol_consistent"] is False

    eb_summary = json.loads((REPO_ROOT / "results" / "tiebreak" / "empirical_bayes" / "summary.json").read_text(encoding="utf-8"))
    opt_params = EmpiricalBayesParams.from_dict(eb_summary["parameters"]["eb_experience_opt"])
    naive_params = make_naive_prior_params()

    sec_bytes = cmp_mod.HELDOUT_WORLD_SECRET.encode("utf-8")
    prev_sec = getattr(canary_world, "_SET_SECRET", None)
    canary_world.set_world_secret(sec_bytes)
    try:
        ep_naive = dataclasses.asdict(run_episode(Env("medium", 800_000), EmpiricalBayesPolicy(params=naive_params, seed=800_000)))
        ep_opt = dataclasses.asdict(run_episode(Env("medium", 800_000), EmpiricalBayesPolicy(params=opt_params, seed=800_000)))
    finally:
        canary_world.set_world_secret(prev_sec)

    r_naive = cmp_mod.analyze_single_episode(ep_naive, verify_with_env=True, world_secret=sec_bytes)
    r_opt = cmp_mod.analyze_single_episode(ep_opt, verify_with_env=True, world_secret=sec_bytes)
    agg = cmp_mod.aggregate_episode_metrics([r_naive, r_opt])
    assert agg["n"] == 2
    assert agg["replay_verification"]["env_replay_verified"] == 2
    assert agg["replay_verification"]["env_replay_pass_rate"] == 1.0


def test_check_comparison_artifacts_rejects_stale_dashes_and_panel_fix_a_violations(tmp_path: Path) -> None:
    summary = json.loads(SUMMARY_JSON_PATH.read_text(encoding="utf-8"))
    md_text = cmp_mod.render_comparison_markdown(summary)

    out_json = tmp_path / "comparison_summary.json"
    out_md = tmp_path / "tiebreak_vs_frontier.md"
    out_json.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    out_md.write_text(md_text, encoding="utf-8")
    assert cmp_mod.check_comparison_artifacts(summary, md_text, out_json, out_md) == []

    out_md.write_text(md_text + "\nextra stale line\n", encoding="utf-8")
    errs_stale_md = cmp_mod.check_comparison_artifacts(summary, md_text, out_json, out_md)
    assert any("stale or modified comparison Markdown" in e for e in errs_stale_md)
    out_md.write_text(md_text, encoding="utf-8")

    out_json.write_text("{\"stale\": true}\n", encoding="utf-8")
    errs_stale_json = cmp_mod.check_comparison_artifacts(summary, md_text, out_json, out_md)
    assert any("stale or modified comparison JSON" in e for e in errs_stale_json)
    out_json.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    bad_dash_md = md_text + f"\nBad dash {chr(0x2014)} here.\n"
    out_md.write_text(bad_dash_md, encoding="utf-8")
    errs_dash = cmp_mod.check_comparison_artifacts(summary, bad_dash_md, out_json, out_md)
    assert any("dash found" in e for e in errs_dash)

    bad_prereg_md = md_text + "\nEvaluated on pre-registered seeds 0..29.\n"
    out_md.write_text(bad_prereg_md, encoding="utf-8")
    errs_prereg = cmp_mod.check_comparison_artifacts(summary, bad_prereg_md, out_json, out_md)
    assert any("Panel Fix A violation" in e for e in errs_prereg)

    bad_seed_summary = copy.deepcopy(summary)
    bad_seed_summary["dev_eval_seed_range"] = "800000..800029"
    out_json.write_text(json.dumps(bad_seed_summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    out_md.write_text(md_text, encoding="utf-8")
    errs_seed = cmp_mod.check_comparison_artifacts(bad_seed_summary, md_text, out_json, out_md)
    assert any("dev_eval_seed_range" in e for e in errs_seed)
