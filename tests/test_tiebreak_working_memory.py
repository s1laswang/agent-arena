from __future__ import annotations

import ast
import io
import json
from pathlib import Path
import shutil
import time
import tokenize

import pytest

import scripts.tiebreak_addendum_pack as addendum_mod
import scripts.tiebreak_experiment_ledger as ledger_mod
import scripts.tiebreak_working_memory_audit as mod

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "tiebreak_working_memory_audit.py"
SUMMARY_JSON_PATH = (
    REPO_ROOT / "results" / "tiebreak" / "working_memory" / "working_memory_summary.json"
)
REPORT_MD_PATH = REPO_ROOT / "docs" / "reports" / "tiebreak_working_memory.md"
SELF_PATH = Path(__file__).resolve()


def test_source_and_artifact_hygiene_and_size() -> None:
    hash_char = chr(35)
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    unicode_minus = chr(0x2212)
    forbidden_imports = {"torch", "transformers", "peft", "vllm", "google", "openai"}

    for py_path in (SCRIPT_PATH, SELF_PATH):
        src = py_path.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(py_path))
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
        assert not [t for t in toks if t.type == tokenize.COMMENT]
        assert hash_char not in src
        assert em_dash not in src
        assert en_dash not in src
        assert unicode_minus not in src
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] not in forbidden_imports
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in forbidden_imports

    assert SUMMARY_JSON_PATH.is_file()
    assert REPORT_MD_PATH.is_file()
    assert SUMMARY_JSON_PATH.stat().st_size < 80 * 1024
    assert not (SUMMARY_JSON_PATH.parent / "summary.json").exists()
    assert not (SUMMARY_JSON_PATH.parent / "table.md").exists()

    for art in (SUMMARY_JSON_PATH, REPORT_MD_PATH):
        txt = art.read_text(encoding="utf-8")
        assert em_dash not in txt
        assert en_dash not in txt
        assert unicode_minus not in txt


def test_seed_hygiene_panel_fix_a_and_panel_fix_e() -> None:
    jobs = mod.build_train_jobs()
    assert len(jobs) == 45
    seeds = [s for _, s in jobs]
    assert seeds == list(range(106_000, 106_045))
    assert len(set(seeds)) == 45
    for tier in ("easy", "medium", "hard"):
        assert sum(1 for t, _ in jobs if t == tier) == 15

    for bad_seed in (0, 29, 9999, 99_999, 200_000, 800_000, 800_059, 900_000, True):
        with pytest.raises(ValueError):
            mod.assert_train_only_seed(bad_seed)

    data = json.loads(SUMMARY_JSON_PATH.read_text(encoding="utf-8"))
    assert data["train_seed_range"] == "106000..106044"
    assert data["train_seed_min"] == 106_000
    assert data["train_seed_max"] == 106_044
    assert data["train_seeds_unique_count"] == 45
    assert data["episodes_per_tier"] == 15

    iso = data["seed_isolation"]
    assert iso["train_only_verified"] is True
    assert iso["heldout_episodes_touched"] == 0
    assert iso["dev_episodes_touched"] == 0
    assert iso["judge_episodes_touched"] == 0
    assert "post-hoc locked, not pre-registered" in iso["panel_fix_a_disclosure"]

    pe = data["panel_fix_e_track_separation"]
    assert pe["open_weight_qwen25_runs_total"] == 19
    assert pe["open_weight_qwen25_runs_above_zero"] == 0
    assert pe["open_weight_qwen25_above_zero_ratio"] == "0 / 19"
    assert pe["non_llm_policies_is_open_weight_llm"] is False


def test_header_token_tax_and_delayed_leak_fifo_eviction() -> None:
    data = json.loads(SUMMARY_JSON_PATH.read_text(encoding="utf-8"))
    ht = data["header_token_tax"]
    assert ht == mod.compute_header_token_tax()

    ref = ht["slurm_44410_reference"]
    assert ref["header_tokens"] == 2842
    assert ref["window_4k_tokens"] == 4096
    assert ref["header_share_pct"] == pytest.approx(69.4)
    assert ref["body_budget_tokens"] == 1254

    hbt = ht["by_tier"]
    assert hbt["easy"]["raw_header_tokens"] == 2731
    assert hbt["medium"]["raw_header_tokens"] == 2877
    assert hbt["hard"]["raw_header_tokens"] == 2936
    assert hbt["mean"]["raw_header_tokens"] == pytest.approx(2848.0)
    for tier in ("easy", "medium", "hard"):
        assert hbt[tier]["compact_header_only_tokens"] < 1000
        assert hbt[tier]["header_reduction_frac"] > 0.64

    nat = data["train_episodes_audit"]["by_scope"]
    assert nat["all"]["n_episodes"] == 45
    assert nat["all"]["raw_openai_chat"]["exceeds_4096_count"] == 45
    assert nat["all"]["raw_openai_chat"]["day1_roster_evicted_4k_sticky_count"] == 45
    assert nat["all"]["raw_openai_chat"]["day1_roster_evicted_4k_sticky_rate"] == 1.0
    assert nat["medium"]["raw_openai_chat"]["canary_map_evicted_before_surface_4k_sticky_rate"] == 1.0
    assert nat["hard"]["raw_openai_chat"]["canary_map_evicted_before_surface_4k_sticky_rate"] == 1.0
    assert nat["all"]["raw_openai_chat"]["canary_map_evicted_at_terminal_4k_sticky_rate"] > 0.99

    wm_all = nat["all"]["compact_working_memory"]
    assert wm_all["state_tokens_max"] < 900
    assert wm_all["all_steps_state_tokens_max"] < 900
    assert wm_all["exceeds_900_any_step_count"] == 0
    assert wm_all["exceeds_2048_prompt_tokens_count"] == 0
    assert wm_all["employee_roster_retention_rate"] == 1.0
    assert wm_all["employee_roster_eviction_rate"] == 0.0
    assert nat["hard"]["compact_working_memory"]["employee_clearances_retained_count"] == 600
    assert wm_all["active_canary_maps_retention_rate"] == 1.0
    assert wm_all["active_canary_maps_eviction_rate"] == 0.0
    assert wm_all["surfaced_leak_candidates_resolved_rate"] == 1.0
    assert wm_all["known_v_exact_match_count"] == 45
    assert wm_all["breakeven_exact_match_count"] == 45
    assert wm_all["compact_state_tracker_parity_rate"] == 1.0

    fh = data["full_horizon_stress_test"]["by_scope"]
    assert fh["easy"]["horizon_days_min"] == 14
    assert fh["medium"]["horizon_days_min"] == 14
    assert fh["hard"]["horizon_days_min"] == 21
    assert fh["all"]["compact_state_tokens_max"] < 900
    assert fh["all"]["exceeds_900_state_tokens_count"] == 0
    assert fh["all"]["lossless_retention_and_tracker_parity_count"] == 45
    assert fh["all"]["lossless_retention_and_tracker_parity_rate"] == 1.0


def test_cross_verification_forensics_and_context_confound() -> None:
    data = json.loads(SUMMARY_JSON_PATH.read_text(encoding="utf-8"))
    cv = data["cross_verification"]

    fv2 = cv["forensics_prior_runs_ws4_v2"]
    assert fv2["header_tokens"] == 2842
    assert fv2["max_len_tokens"] == 4096
    assert fv2["body_budget_tokens"] == 1254
    assert fv2["dropped_list_employees_turns"] == 68
    assert fv2["total_list_employees_turns"] == 70
    assert fv2["dropped_list_employees_pct"] == pytest.approx(97.1)

    c450 = cv["context_confound_all_450_verda"]
    assert c450["n_episodes"] == 450
    assert c450["plant_canary_evicted_4k_count"] == 1162
    assert c450["plant_canary_ok_calls_in_prefix"] == 1186
    assert c450["plant_canary_evicted_4k_pct_1d"] == pytest.approx(98.0)
    assert c450["compact_canary_map_evicted_count"] == 0
    assert c450["compact_canary_map_evicted_pct"] == pytest.approx(0.0)
    assert c450["compact_exceeds_900_state_tokens_count"] == 0


def test_offline_check_speed_root_flag_tamper_detection_and_ledger_disjointness(
    tmp_path: Path,
) -> None:
    t0 = time.perf_counter()
    assert mod.main(["--check"]) == 0
    assert (time.perf_counter() - t0) < 10.0

    rel_files = (
        "scripts/tiebreak_working_memory_audit.py",
        "tests/test_tiebreak_working_memory.py",
        "results/tiebreak/forensics_prior_runs.json",
        "results/tiebreak/context_confound/audit_summary.json",
        "results/tiebreak/experiment_ledger.json",
        "results/tiebreak/working_memory/working_memory_summary.json",
        "docs/reports/tiebreak_working_memory.md",
    )
    for rel in rel_files:
        dst = tmp_path / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / rel, dst)

    t1 = time.perf_counter()
    assert mod.main(["--root", str(tmp_path), "--check"]) == 0
    assert (time.perf_counter() - t1) < 10.0

    md_copy = tmp_path / "docs" / "reports" / "tiebreak_working_memory.md"
    orig_md = md_copy.read_text(encoding="utf-8")
    md_copy.write_text(orig_md.replace("98.0%", "42.0%"), encoding="utf-8")
    assert mod.main(["--root", str(tmp_path), "--check"]) == 1
    md_copy.write_text(orig_md, encoding="utf-8")

    json_copy = tmp_path / "results" / "tiebreak" / "working_memory" / "working_memory_summary.json"
    orig_json = json_copy.read_text(encoding="utf-8")
    tampered = json.loads(orig_json)
    tampered["train_episodes_audit"]["by_scope"]["all"]["compact_working_memory"][
        "employee_roster_retention_rate"
    ] = 0.5
    json_copy.write_text(json.dumps(tampered, indent=2) + "\n", encoding="utf-8")
    assert mod.main(["--root", str(tmp_path), "--check"]) == 1
    json_copy.write_text(orig_json, encoding="utf-8")

    forbidden_sib = json_copy.parent / "summary.json"
    forbidden_sib.write_text("{}", encoding="utf-8")
    assert mod.main(["--root", str(tmp_path), "--check"]) == 1
    forbidden_sib.unlink()

    assert ledger_mod.main(["--check"]) == 0
    assert addendum_mod.main(["--check"]) == 0
