from __future__ import annotations

import ast
import copy
import io
import json
import sys
import tokenize
from pathlib import Path
from typing import Any

import pytest

import scripts.tiebreak_context_confound_audit as audit
import scripts.verify_tiebreak_submission as sub_gate

REPO_ROOT = Path(__file__).resolve().parents[1]
AUDIT_SCRIPT_PATH = REPO_ROOT / "scripts" / "tiebreak_context_confound_audit.py"
SELF_PATH = Path(__file__).resolve()
AUDIT_JSON_PATH = REPO_ROOT / "results" / "tiebreak" / "context_confound" / "audit_summary.json"
LEGACY_JSON_PATH = REPO_ROOT / "results" / "tiebreak" / "context_confound" / "summary.json"
REPORT_MD_PATH = REPO_ROOT / "results" / "tiebreak" / "context_confound" / "report.md"


@pytest.fixture(scope="module")
def computed_summary() -> dict[str, Any]:
    return audit.build_audit_summary(repo_root=REPO_ROOT, allow_git_readout=True)


def _write_mini_verda_repo(dst_root: Path) -> Path:
    src_eps = audit.read_jsonl(REPO_ROOT / audit.VERDA_RUN_SPECS[0]["episodes_rel"])
    mini_by_tier: list[dict[str, Any]] = []
    for tier in ("easy", "medium", "hard"):
        ep_t = next(e for e in src_eps if e["tier"] == tier)
        mini_by_tier.append(ep_t)
    lines = "\n".join(json.dumps(e) for e in mini_by_tier) + "\n"
    for spec in audit.VERDA_RUN_SPECS:
        p = dst_root / spec["episodes_rel"]
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(lines, encoding="utf-8")
    return dst_root


def test_source_and_artifact_hygiene() -> None:
    hash_char = chr(35)
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    forbidden_roots = {"torch", "transformers", "peft", "mlx", "mlx_lm"}

    for py_path in (AUDIT_SCRIPT_PATH, SELF_PATH):
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
                    assert alias.name.split(".")[0] not in forbidden_roots
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in forbidden_roots

    assert not LEGACY_JSON_PATH.exists()
    assert AUDIT_JSON_PATH.is_file()
    assert REPORT_MD_PATH.is_file()

    for artifact in (AUDIT_JSON_PATH, REPORT_MD_PATH):
        txt = artifact.read_text(encoding="utf-8")
        assert em_dash not in txt
        assert en_dash not in txt
        assert txt.isascii()
        assert "pre-register" not in txt.lower()

    md_txt = REPORT_MD_PATH.read_text(encoding="utf-8")
    assert "post-hoc locked" in md_txt

    assert "torch" not in sys.modules
    assert "transformers" not in sys.modules


def test_offline_fallback_and_committed_byte_identity(computed_summary: dict[str, Any]) -> None:
    git_readout = audit.load_silas_0507_readout(REPO_ROOT, allow_git=True)
    offline_readout = audit.load_silas_0507_readout(REPO_ROOT, allow_git=False)
    assert git_readout == offline_readout

    s0_180 = computed_summary["pooled_views"]["v3_4k_s0_pooled_180"]
    assert audit.build_inference_length_confound_section(
        s0_180, git_readout
    ) == audit.build_inference_length_confound_section(s0_180, offline_readout)

    expected_json = json.dumps(computed_summary, indent=2) + "\n"
    expected_md = audit.render_markdown_report(computed_summary)

    assert AUDIT_JSON_PATH.read_text(encoding="utf-8") == expected_json
    assert REPORT_MD_PATH.read_text(encoding="utf-8") == expected_md
    assert audit.validate_audit_artifacts(computed_summary, md_text=expected_md) == []


def test_eviction_compact_state_and_belief_replay_metrics(computed_summary: dict[str, Any]) -> None:
    assert computed_summary["n"] == 450
    assert len(computed_summary["runs"]) == 5

    raw_json_str = json.dumps(computed_summary)
    assert '"train_seeds"' not in raw_json_str
    assert '"eval_seeds"' not in raw_json_str
    seed_ranges = computed_summary["audited_heldout_seed_ranges"]
    assert seed_ranges["v3-verda-s0"] == "800000..800029"
    assert seed_ranges["v3-4k-s0-off30"] == "800030..800059"
    assert seed_ranges["v3-4k-s0@8k"] == "800000..800029"
    assert seed_ranges["v3-8k-s3"] == "800000..800029"

    all_450 = computed_summary["pooled_views"]["all_450_verda"]["all"]
    rt = all_450["raw_transcript"]
    ct = all_450["compact_transcript"]
    br = all_450["belief_replay"]

    assert rt["exceeds_4096_count"] == 450
    assert rt["exceeds_4096_pct"] == 100.0
    assert rt["plant_canary_ok_calls_in_prefix"] == 1186
    assert 92.0 <= rt["plant_canary_evicted_4k_pct"] <= 98.5
    assert 92.0 <= rt["plant_canary_suffix_evicted_4k_pct"] <= 98.5
    assert 80.0 <= rt["plant_canary_evicted_8k_pct"] <= 86.0
    assert 80.0 <= rt["plant_canary_suffix_evicted_8k_pct"] <= 85.0

    s1_rt = computed_summary["runs"]["v3-verda-8k-s1"]["by_tier"]["all"]["raw_transcript"]
    assert 50.5 <= s1_rt["plant_canary_suffix_evicted_8k_pct"] <= 52.0
    assert 56.0 <= s1_rt["plant_canary_evicted_8k_pct"] <= 57.5

    assert ct["state_tokens_max"] < 900
    assert ct["exceeds_900_state_tokens_count"] == 0
    assert ct["tokens_max"] < 1800
    assert ct["exceeds_1800_tokens_count"] == 0
    assert ct["canary_map_evicted_count"] == 0
    assert ct["canary_map_evicted_pct"] == 0.0
    assert ct["roster_evicted_count"] == 0
    assert ct["roster_evicted_pct"] == 0.0

    stress = computed_summary["compact_hard_21day_stress_check"]
    assert stress["available"] is True
    assert stress["n_hard_reference_episodes"] == 60
    assert stress["compact_state_tokens_max"] < 900
    assert stress["exceeds_900_state_tokens_count"] == 0
    assert stress["exceeds_1800_tokens_count"] == 0
    assert stress["canary_map_evicted_count"] == 0

    assert br["accused_episodes"] == 181
    assert br["correct_accusations"] == 18
    assert br["below_breakeven_count"] == 173
    assert br["below_breakeven_pct"] == 95.58

    gap = computed_summary["off_policy_and_seed_divergence_diagnosis"]["rollout_vs_solver_gap"]
    assert gap["v3_4k_s0"]["train_forced_accuse_last100"] == 0.8916
    assert gap["v3_4k_s0"]["heldout_precision"] == 0.1579
    assert gap["v3_8k_s1"]["heldout_accused"] == 85
    assert gap["v3_8k_s1"]["heldout_precision"] == 0.0941
    assert gap["v3_8k_s2"]["heldout_abstain"] == 84
    assert gap["v3_8k_s2"]["rejected_accuse_calls"] == 784


def test_silas_0507_8k_confound_and_paired_s3_alignment(computed_summary: dict[str, Any]) -> None:
    conf = computed_summary["inference_length_confound_v3_4k_s0_at_8k"]
    assert conf["adapter_id"] == "v3-4k-s0"
    assert conf["adapter_sha256_prefix"] == "3d0cd43b8037"

    e4 = conf["eval_at_4k"]["by_tier"]
    assert e4["all"]["n"] == 180
    assert e4["all"]["mean_score"] == -0.147
    assert e4["all"]["ci95"] == 0.063
    assert e4["medium"]["accused_rate"] == 0.00
    assert e4["hard"]["accused_rate"] == 0.03

    e8 = conf["eval_at_8k"]
    assert e8["run_label"] == "v3-4k-s0@8k"
    assert e8["max_ctx"] == 8192
    assert e8["world_secret_tag"] == "1ca0c2a64d"
    assert e8["n"] == 90
    assert e8["medium_hard_correct_count"] == 0
    assert e8["medium_hard_accused_count"] == 51
    assert e8["by_tier"]["all"]["mean_score"] == -0.716
    assert e8["by_tier"]["all"]["ci95"] == 0.105
    assert e8["by_tier"]["medium"]["accused_rate"] == 0.80
    assert e8["by_tier"]["hard"]["accused_rate"] == 0.90
    assert e8["by_tier"]["medium"]["accuracy"] == 0.00
    assert e8["by_tier"]["hard"]["accuracy"] == 0.00

    d84 = conf["two_sample_delta_8k_minus_4k"]["all"]
    assert d84["mean_delta"] == -0.568
    assert d84["ci95"] == 0.123
    assert d84["n_pair"] == "90 vs 180"

    s3 = conf["paired_8k_trained_s3_comparison"]
    assert s3["run_label"] == "v3-8k-s3"
    assert s3["steps"] == 344
    assert s3["world_secret_tag"] == "1ca0c2a64d"
    assert s3["verified_identical_rosters"] == "60/60"
    assert s3["n"] == 90
    assert s3["mean_score"] == -0.788
    assert s3["ci95"] == 0.117
    assert s3["accused_rate"] == 0.96
    assert s3["accuracy"] == 0.09
    assert s3["paired_delta_vs_v3_4k_s0_at_8k"] == -0.073
    assert s3["paired_ci95"] == 0.173


def test_ws4_table_parser_cli_and_validator_rejections(
    tmp_path: Path,
    computed_summary: dict[str, Any],
) -> None:
    minus_u = chr(0x2212)
    pm_u = chr(0x00B1)
    synthetic_table = "\n".join(
        [
            "| m | r | s | tier | n | sc | acc | cor | abs | val | db | dv2 | dv3 |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
            f"| v3-4k-s0@8k | r | 800000..800029 | easy | 30 | {minus_u}0.447 {pm_u} 0.233 | 0.63 | 0.10 | 0.37 | 0.99 | x | x | -0.038 {pm_u} 0.285 (30 vs 60) |",
            f"| v3-4k-s0@8k | r | 800000..800029 | medium | 30 | -0.800 +/- 0.146 | 0.80 | 0.00 | 0.20 | 1.00 | x | x | -0.800 +/- 0.146 (30 vs 60) |",
            f"| v3-4k-s0@8k | r | 800000..800029 | hard | 30 | -0.900 +/- 0.109 | 0.90 | 0.00 | 0.10 | 1.00 | x | x | -0.867 +/- 0.118 (30 vs 60) |",
            f"| v3-4k-s0@8k | r | 800000..800029 | all | 90 | -0.716 +/- 0.105 | 0.78 | 0.03 | 0.22 | 0.99 | x | x | -0.568 +/- 0.123 (90 vs 180) |",
            f"| v3-8k-s3 | r | 800000..800029 | easy | 30 | -0.643 +/- 0.249 | 0.90 | 0.13 | 0.10 | 0.82 | x | x | -0.234 +/- 0.298 (30 vs 60) |",
            f"| v3-8k-s3 | r | 800000..800029 | medium | 30 | -0.878 +/- 0.166 | 1.00 | 0.07 | 0.00 | 1.00 | x | x | -0.878 +/- 0.166 (30 vs 60) |",
            f"| v3-8k-s3 | r | 800000..800029 | hard | 30 | -0.843 +/- 0.178 | 0.97 | 0.07 | 0.03 | 0.96 | x | x | -0.810 +/- 0.183 (30 vs 60) |",
            f"| v3-8k-s3 | r | 800000..800029 | all | 90 | -0.788 +/- 0.117 | 0.96 | 0.09 | 0.04 | 0.94 | x | x | -0.641 +/- 0.132 (90 vs 180) |",
        ]
    )
    parsed = audit.parse_ws4_table_readout(synthetic_table)
    assert parsed == audit._SILAS_0507_READOUT_FALLBACK

    fallback_from_empty = audit.load_silas_0507_readout(tmp_path, allow_git=True)
    assert fallback_from_empty == audit._SILAS_0507_READOUT_FALLBACK

    bad_dash = copy.deepcopy(computed_summary)
    bad_dash["notes"] = "bad " + chr(0x2014) + " note"
    assert any("dash" in e for e in audit.validate_audit_artifacts(bad_dash))

    bad_prereg = copy.deepcopy(computed_summary)
    bad_prereg["notes"] = "pre-registered dev seeds 0..29"
    assert any("Panel Fix A" in e for e in audit.validate_audit_artifacts(bad_prereg))

    bad_compact = copy.deepcopy(computed_summary)
    bad_compact["runs"]["v2-off30"]["by_tier"]["easy"]["compact_transcript"]["state_tokens_max"] = 950
    assert any("state_tokens_max" in e for e in audit.validate_audit_artifacts(bad_compact))

    mini_repo = _write_mini_verda_repo(tmp_path / "mini_repo")
    rc_write = audit.main(["--repo-root", str(mini_repo)])
    assert rc_write == 0
    rc_check = audit.main(["--repo-root", str(mini_repo), "--check"])
    assert rc_check == 0

    (mini_repo / "results" / "tiebreak" / "context_confound" / "summary.json").write_text("{}", encoding="utf-8")
    rc_collide = audit.main(["--repo-root", str(mini_repo), "--check"])
    assert rc_collide == 1


def test_submission_verifier_provenance_and_hygiene_pass_with_w1_artifacts() -> None:
    prov = sub_gate.check_seed_and_secret_provenance(root=REPO_ROOT, strict=True)
    assert prov.passed is True
    assert prov.errors == []

    hyg = sub_gate.check_hygiene_and_panel_fix_a(root=REPO_ROOT, strict=True)
    assert hyg.passed is True
    assert hyg.errors == []
