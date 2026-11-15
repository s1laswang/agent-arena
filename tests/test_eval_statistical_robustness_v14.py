from __future__ import annotations

import ast
import importlib.util
import io
import json
import re
import sys
import tokenize
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if sys.path[:1] != [str(ROOT)]:
    sys.path.insert(0, str(ROOT))

SCRIPT_PATH = ROOT / "scripts/eval_statistical_robustness_v14.py"
TEST_PATH = ROOT / "tests/test_eval_statistical_robustness_v14.py"
JSON_PATH = ROOT / "results/eval_v14/statistical_robustness_v14.json"
MD_PATH = ROOT / "docs/reports/statistical_robustness_v14.md"

_SPEC = importlib.util.spec_from_file_location("eval_statistical_robustness_v14", SCRIPT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
sr = importlib.util.module_from_spec(_SPEC)
sys.modules["eval_statistical_robustness_v14"] = sr
_SPEC.loader.exec_module(sr)


@pytest.fixture(scope="module")
def payload() -> dict:
    return sr.build_payload(ROOT)


def test_committed_artifacts_check_mode_and_size(payload: dict) -> None:
    assert JSON_PATH.exists()
    assert MD_PATH.exists()
    assert JSON_PATH.stat().st_size < 45 * 1024
    assert sr.main(["--check"]) == 0
    committed = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    assert committed["schema_version"] == "statistical_robustness_v14.v1"
    assert committed["n_primary_seeds_per_tier"] == 30
    assert committed["primary_seeds"] == "0-29"
    assert "671ed96" in committed["primary_seeds_lock_note"]
    assert "not pre-registered" in committed["primary_seeds_lock_note"]
    assert committed["headline_table_crosscheck"]["passed"] is True
    assert committed["headline_table_crosscheck"]["max_abs_diff"] <= 1e-9


def test_shallow_ci_zero_git_subprocesses_and_detached_root(tmp_path: Path, payload: dict) -> None:
    tree = ast.parse(SCRIPT_PATH.read_text(encoding="utf-8"))
    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_names.add(node.module.split(".")[0])
    assert "subprocess" not in imported_names

    fake_root = tmp_path / "shallow_no_git_repo"
    fake_root.mkdir()
    assert not (fake_root / ".git").exists()
    (fake_root / "data").symlink_to(ROOT / "data", target_is_directory=True)
    (fake_root / "results").mkdir()
    (fake_root / "results/eval_v14").mkdir()
    (fake_root / "results/eval_v14/headline_gap_table_v14.json").symlink_to(
        ROOT / "results/eval_v14/headline_gap_table_v14.json"
    )
    (fake_root / "results/harbor").symlink_to(ROOT / "results/harbor", target_is_directory=True)

    out_json = fake_root / "results/eval_v14/statistical_robustness_v14.json"
    out_md = fake_root / "docs/reports/statistical_robustness_v14.md"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_bytes(JSON_PATH.read_bytes())
    out_md.write_bytes(MD_PATH.read_bytes())
    assert sr.main(["--check", "--root", str(fake_root), "--out-json", str(out_json), "--out-md", str(out_md)]) == 0


def test_four_way_paired_inference_and_gpt55_abstain_handling(payload: dict) -> None:
    by_key = {(c["cohort_id"], c["tier"]): c for c in payload["cohorts"]}
    assert set(by_key.keys()) == {
        ("opencode-gemini-4-carbon", "hard"),
        ("inproc-gemini-4-carbon", "hard"),
        ("opencode-gemini-3.5-flash", "hard"),
        ("opencode-gpt-5.5", "hard"),
        ("opencode-gemini-4-carbon", "medium"),
        ("inproc-gemini-4-carbon", "medium"),
    }

    oc_h = by_key[("opencode-gemini-4-carbon", "hard")]
    assert oc_h["seeds"] == list(range(30))
    oc_la = oc_h["inference_matrix"]["luck_adjusted"]
    assert abs(oc_la["point_ratio"] - 0.7201029448) < 1e-9
    assert oc_la["percentile_bootstrap_95_ci"][1] < 1.0
    assert oc_la["bca_bootstrap_95_ci"][1] < 1.0
    assert oc_la["fieller_95_ci"][1] < 1.0
    assert oc_la["all_three_cis_below_parity"] is True
    assert oc_la["sign_flip_perm_p"] < 0.05
    assert abs(oc_la["wilcoxon_signed_rank_p"] - 0.0220988542) < 1e-9

    gpt_h = by_key[("opencode-gpt-5.5", "hard")]
    assert gpt_h["abstained_seeds"] == [0, 17]
    assert gpt_h["accused_meta_v_final_count"] == 28
    gpt_raw = gpt_h["inference_matrix"]["raw"]
    gpt_la = gpt_h["inference_matrix"]["luck_adjusted"]
    assert abs(gpt_raw["point_ratio"] - 1.0093520374) < 1e-9
    assert abs(gpt_la["point_ratio"] - 0.8366849368) < 1e-9
    assert gpt_raw["all_three_cis_straddle_parity"] is True
    assert gpt_la["all_three_cis_straddle_parity"] is True


def test_leave_one_seed_out_jackknife_bounds(payload: dict) -> None:
    by_key = {(c["cohort_id"], c["tier"]): c for c in payload["cohorts"]}
    for c in payload["cohorts"]:
        loo = c["leave_one_seed_out"]
        assert loo["n_subsets"] == 30
        assert loo["subset_size"] == 29
        assert loo["dropped_seeds"] == list(range(30))
        assert len(loo["loo_raw_ratio"]) == 30
        assert len(loo["loo_luck_adj_ratio"]) == 30
        assert len(loo["loo_raw_paired_diff"]) == 30
        assert len(loo["loo_luck_adj_paired_diff"]) == 30

    oc_loo = by_key[("opencode-gemini-4-carbon", "hard")]["leave_one_seed_out"]
    assert oc_loo["luck_adj_ratio_bounds"]["count_below_threshold"] == 30
    assert oc_loo["luck_adj_ratio_bounds"]["max"] < 1.0
    assert oc_loo["raw_ratio_bounds"]["count_below_threshold"] == 30
    assert oc_loo["raw_ratio_bounds"]["max"] < 1.0

    gpt_loo = by_key[("opencode-gpt-5.5", "hard")]["leave_one_seed_out"]
    assert gpt_loo["raw_ratio_bounds"]["min"] < 1.0 < gpt_loo["raw_ratio_bounds"]["max"]
    assert 0 < gpt_loo["raw_ratio_bounds"]["count_below_threshold"] < 30


def test_harbor_rehearsal_sensitivity(payload: dict) -> None:
    harbor = payload["harbor_rehearsal_sensitivity"]
    assert harbor["tag"] == "afterquery-final"
    assert harbor["commit_sha_short"] == "1bc3e281"
    assert harbor["mcp_only_hard_gap_reproduced_in_harbor"] is False
    assert abs(harbor["oracle_10_task_mean"] - 0.506) < 1e-9
    assert harbor["do_nothing_mean"] == 0.0
    assert harbor["stop_early_mean"] == 0.0

    runs = {r["run_id"]: r for r in harbor["runs"]}
    assert runs["opencode-1"]["reported_ratio_pct"] == 93
    assert abs(runs["opencode-1"]["mean_score"] - 0.472) < 1e-9
    assert runs["opencode-2"]["reported_ratio_pct"] == 116
    assert abs(runs["opencode-2"]["mean_score"] - 0.585) < 1e-9
    assert runs["opencode-3-final"]["reported_ratio_pct"] == 131
    assert runs["opencode-3-final"]["n_valid"] == 9
    assert runs["opencode-3-final"]["n_finished_after_0830_cutoff"] == 5
    assert abs(runs["opencode-3-final"]["mean_score"] - 0.626) < 1e-9
    assert runs["opencode-3-snapshot-0852-partial"]["reported_ratio_pct"] == 153
    assert runs["opencode-3-snapshot-0852-partial"]["n_valid"] == 7


def test_statistical_primitives_unit() -> None:
    assert abs(sr.student_t_ppf(0.975, 29) - 2.0452296421327034) < 1e-12
    assert abs(sr.student_t_ppf(0.975, 9) - 2.262157162798205) < 1e-12
    f_ident = [0.5 + 0.01 * i for i in range(30)]
    inf = sr.compute_four_way_inference(f_ident, f_ident)
    assert inf["point_ratio"] == 1.0
    assert inf["point_paired_diff"] == 0.0
    assert inf["sign_flip_perm_p"] == 1.0
    assert inf["wilcoxon_signed_rank_p"] == 1.0


def test_zero_comments_zero_forbidden_chars_and_no_mole_ids() -> None:
    for py_path in (SCRIPT_PATH, TEST_PATH):
        src = py_path.read_text(encoding="utf-8")
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        comments = [t for t in tokens if t.type == tokenize.COMMENT]
        assert comments == [], f"Found comment tokens in {py_path}: {comments}"

    for path in (SCRIPT_PATH, TEST_PATH, JSON_PATH, MD_PATH):
        text = path.read_text(encoding="utf-8")
        assert "\u2013" not in text
        assert "\u2014" not in text
        assert "\u00b1" not in text

    for path in (JSON_PATH, MD_PATH):
        text = path.read_text(encoding="utf-8")
        assert re.search(r"\be(?:0[1-9]|[1-3][0-9]|40)\b", text) is None
