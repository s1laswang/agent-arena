from __future__ import annotations

import copy
import importlib.util
import io
import itertools
import json
import math
import random
import re
import sys
import tokenize
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.analysis.gap import mean_ci

SCRIPT_PATH = ROOT / "scripts/eval_statistical_robustness_v14.py"
TEST_PATH = ROOT / "tests/test_eval_statistical_robustness_v14.py"
JSON_PATH = ROOT / "results/eval_v14/statistical_robustness_v14.json"
MD_PATH = ROOT / "docs/reports/statistical_robustness_v14.md"

HASH_CHAR = chr(35)
EN_DASH = chr(0x2013)
EM_DASH = chr(0x2014)
PLUS_MINUS = chr(0x00B1)
CO_AUTHORED_TAG = "Co-Authored-" + "By"

_SPEC = importlib.util.spec_from_file_location("eval_statistical_robustness_v14", SCRIPT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
sr = importlib.util.module_from_spec(_SPEC)
sys.modules["eval_statistical_robustness_v14"] = sr
_SPEC.loader.exec_module(sr)

_ORIG_BOOT_WEIGHTS = sr._boot_weights


def _fast_exact_boot_weights(
    n: int,
    resamples: int = sr.BOOTSTRAP_RESAMPLES,
    rng_seed: int = sr.RNG_SEED,
) -> np.ndarray:
    key = (n, resamples, rng_seed)
    if key not in sr._BOOT_CACHE:
        total = resamples * n
        rng = random.Random(rng_seed)
        k = n.bit_length()
        chunks: list[np.ndarray] = []
        got = 0
        accept_p = n / float(1 << k)
        while got < total:
            need = int((total - got) / accept_p * 1.15) + 64
            raw = np.fromiter(map(rng.getrandbits, itertools.repeat(k, need)), dtype=np.int64, count=need)
            ok = raw[raw < n]
            chunks.append(ok)
            got += int(ok.shape[0])
        cols = np.concatenate(chunks)[:total] if len(chunks) > 1 else chunks[0][:total]
        flat_idx = np.repeat(np.arange(resamples, dtype=np.int64) * n, n) + cols
        counts = np.bincount(flat_idx, minlength=total).reshape(resamples, n)
        sr._BOOT_CACHE[key] = counts * (1.0 / n)
    return sr._BOOT_CACHE[key]


sr._boot_weights = _fast_exact_boot_weights


def _write_seed_slice_dir(src_jsonl: Path, dst_dir: Path, seeds: set[int]) -> Path:
    dst_dir.mkdir(parents=True, exist_ok=True)
    picked: list[str] = []
    found: set[int] = set()
    with src_jsonl.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            ep = json.loads(line)
            sd = int(ep["seed"])
            if sd in seeds and sd not in found:
                picked.append(line if line.endswith("\n") else line + "\n")
                found.add(sd)
                if found == seeds:
                    break
    assert found == seeds
    (dst_dir / "episodes.jsonl").write_text("".join(picked), encoding="utf-8")
    return dst_dir


@pytest.fixture(scope="module")
def payload() -> dict:
    assert JSON_PATH.is_file()
    assert MD_PATH.is_file()
    return json.loads(JSON_PATH.read_text(encoding="utf-8"))


def test_committed_artifacts_check_mode_and_size(
    payload: dict,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert JSON_PATH.exists()
    assert MD_PATH.exists()
    assert JSON_PATH.stat().st_size < 45 * 1024
    assert JSON_PATH.stat().st_size < sr.MAX_JSON_BYTES

    assert payload["schema_version"] == "statistical_robustness_v14.v1"
    assert payload["tiers_version"] == "v1.4"
    assert payload["n_primary_seeds_per_tier"] == 30
    assert payload["primary_seeds"] == "0-29"
    assert "671ed96" in payload["primary_seeds_lock_note"]
    assert "not pre-registered" in payload["primary_seeds_lock_note"]
    assert payload["headline_table_crosscheck"]["passed"] is True
    assert payload["headline_table_crosscheck"]["max_abs_diff"] <= 1e-9

    assert sr.render_markdown(payload) == MD_PATH.read_text(encoding="utf-8")
    roundtrip = json.loads(sr._compact_json_dumps(payload))
    rt_errs: list[str] = []
    sr._compare_values(roundtrip, payload, "root", 1e-9, rt_errs)
    assert rt_errs == []

    live_cc = sr._crosscheck_headline_json(ROOT, payload["cohorts"])
    assert live_cc["passed"] is True and live_cc["checked_scalar_fields"] == 96
    assert live_cc["max_abs_diff"] <= 1e-9

    with monkeypatch.context() as mp_fast:
        mp_fast.setattr(sr, "BOOTSTRAP_RESAMPLES", 200)
        mp_fast.setattr(sr.sign_flip_permutation_pvalue, "__defaults__", (200, sr.RNG_SEED, 1e-12))
        live_harbor = sr.parse_harbor_rehearsal(ROOT)
    exp_harbor = payload["harbor_rehearsal_sensitivity"]
    assert live_harbor["tag"] == exp_harbor["tag"]
    assert live_harbor["commit_sha_full"] == exp_harbor["commit_sha_full"]
    assert live_harbor["oracle_10_task_mean"] == exp_harbor["oracle_10_task_mean"]
    assert live_harbor["spread_across_3_runs"] == exp_harbor["spread_across_3_runs"]
    for got_r, exp_r in zip(live_harbor["runs"], exp_harbor["runs"]):
        for k in ("run_id", "n_valid", "mean_score", "oracle_same_tasks_mean", "ratio_vs_oracle", "paired_diff"):
            assert got_r[k] == exp_r[k]
        if "fieller_95_ci" in exp_r:
            assert got_r["fieller_95_ci"] == exp_r["fieller_95_ci"]
        if "wilcoxon_signed_rank_p" in exp_r:
            assert got_r["wilcoxon_signed_rank_p"] == exp_r["wilcoxon_signed_rank_p"]

    slice_seeds = {0}
    oc_dir = _write_seed_slice_dir(
        ROOT / "data/runs/committed/v1.4/opencode-gemini-4-carbon/medium/episodes.jsonl",
        tmp_path / "oc_med",
        slice_seeds,
    )
    gpt_dir = _write_seed_slice_dir(
        ROOT / "data/runs/committed/v1.4/opencode-gpt-5.5/hard/episodes.jsonl",
        tmp_path / "gpt_hard",
        slice_seeds,
    )
    sol_dir = _write_seed_slice_dir(
        ROOT / "data/runs/committed/v1.4/reference/solver-medium-20261114-121126/episodes.jsonl",
        tmp_path / "sol_med",
        slice_seeds,
    )

    oc_series = sr._load_dir_seed_series(oc_dir, "opencode:google/gemini-4-carbon", "medium")
    gpt_series = sr._load_dir_seed_series(gpt_dir, "opencode:openai/gpt-5.5", "hard")
    sol_series = sr._load_dir_seed_series(sol_dir, "solver", "medium")
    assert set(oc_series) == slice_seeds
    assert set(gpt_series) == slice_seeds
    assert set(sol_series) == slice_seeds

    assert gpt_series[0]["abstained"] is True
    assert gpt_series[0]["raw_score"] == 0.0 and gpt_series[0]["luck_adj_score"] == 0.0
    assert gpt_series[0]["v_final_value"] is None

    by_key = {(c["cohort_id"], c["tier"]): c for c in payload["cohorts"]}
    oc_m = by_key[("opencode-gemini-4-carbon", "medium")]
    oc_raw_inf = oc_m["inference_matrix"]["raw"]
    oc_la_inf = oc_m["inference_matrix"]["luck_adjusted"]
    oc_loo = oc_m["leave_one_seed_out"]
    exp_raw_loo = (30.0 * oc_raw_inf["frontier_mean"] - oc_series[0]["raw_score"]) / (
        30.0 * oc_raw_inf["solver_mean"] - sol_series[0]["raw_score"]
    )
    exp_la_loo = (30.0 * oc_la_inf["frontier_mean"] - oc_series[0]["luck_adj_score"]) / (
        30.0 * oc_la_inf["solver_mean"] - sol_series[0]["luck_adj_score"]
    )
    assert math.isclose(exp_raw_loo, oc_loo["loo_raw_ratio"][0], abs_tol=1e-8)
    assert math.isclose(exp_la_loo, oc_loo["loo_luck_adj_ratio"][0], abs_tol=1e-8)

    diffs_2 = [0.2, 0.5]
    _, hw_gap = mean_ci(diffs_2)
    assert math.isclose(sr.mean_normal_ci_halfwidth(diffs_2), hw_gap, abs_tol=1e-12)

    monkeypatch.setattr(sr, "build_payload", lambda _root=sr.ROOT: copy.deepcopy(payload))
    assert sr.main(["--check"]) == 0
    assert "OK: statistical_robustness_v14" in capsys.readouterr().out


def test_cli_write_and_check_tamper_detection(
    payload: dict,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sr, "build_payload", lambda _root=sr.ROOT: copy.deepcopy(payload))
    good_json = tmp_path / "good.json"
    good_md = tmp_path / "good.md"
    assert sr.main(["--out-json", str(good_json), "--out-md", str(good_md)]) == 0

    tampered = json.loads(good_json.read_text(encoding="utf-8"))
    tampered["cohorts"][0]["inference_matrix"]["luck_adjusted"]["point_ratio"] += 0.01
    bad_json = tmp_path / "bad.json"
    bad_json.write_text(json.dumps(tampered), encoding="utf-8")
    assert sr.main(["--check", "--out-json", str(bad_json), "--out-md", str(good_md)]) == 1

    bad_md = tmp_path / "bad.md"
    bad_md.write_text(good_md.read_text(encoding="utf-8") + "\ndrift\n", encoding="utf-8")
    assert sr.main(["--check", "--out-json", str(good_json), "--out-md", str(bad_md)]) == 1

    oversized = tmp_path / "oversized.json"
    oversized.write_text(good_json.read_text(encoding="utf-8") + " " * (sr.MAX_JSON_BYTES + 10), encoding="utf-8")
    assert sr.main(["--check", "--out-json", str(oversized), "--out-md", str(good_md)]) == 1

    leaked_md = tmp_path / "leaked.md"
    leaked_md.write_text(good_md.read_text(encoding="utf-8") + "\nmole e" + "07\n", encoding="utf-8")
    assert sr.main(["--check", "--out-json", str(good_json), "--out-md", str(leaked_md)]) == 1


def test_shallow_ci_zero_git_subprocesses_and_detached_root(
    tmp_path: Path,
    payload: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script_src = SCRIPT_PATH.read_text(encoding="utf-8")
    assert re.search(r"^\s*(?:import|from)\s+subprocess\b", script_src, flags=re.M) is None
    assert "subprocess" not in sr.__dict__

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

    cc_detached = sr._crosscheck_headline_json(fake_root, payload["cohorts"])
    assert cc_detached["passed"] is True
    assert "sha: 1bc3e281" in (fake_root / "results/harbor/rehearsal/BUILD.txt").read_text(encoding="utf-8")

    def _fast_detached_build(repo_root: Path = sr.ROOT) -> dict:
        assert not (repo_root / ".git").exists()
        assert (repo_root / "results/eval_v14/headline_gap_table_v14.json").is_file()
        assert (repo_root / "results/harbor/rehearsal/TABLE.md").is_file()
        return copy.deepcopy(payload)

    monkeypatch.setattr(sr, "build_payload", _fast_detached_build)

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


def test_statistical_primitives_unit(monkeypatch: pytest.MonkeyPatch) -> None:
    sr._BOOT_CACHE.pop((10, 50, 99), None)
    w_orig = _ORIG_BOOT_WEIGHTS(10, 50, 99)
    sr._BOOT_CACHE.pop((10, 50, 99), None)
    w_fast = _fast_exact_boot_weights(10, 50, 99)
    assert np.allclose(w_orig, w_fast, atol=1e-15)
    assert abs(sr.student_t_ppf(0.975, 29) - 2.0452296421327034) < 1e-12
    assert abs(sr.student_t_ppf(0.975, 9) - 2.262157162798205) < 1e-12
    monkeypatch.setattr(sr, "BOOTSTRAP_RESAMPLES", 200)
    f_ident = [0.5 + 0.01 * i for i in range(30)]
    inf = sr.compute_four_way_inference(f_ident, f_ident)
    assert inf["point_ratio"] == 1.0
    assert inf["point_paired_diff"] == 0.0
    assert inf["sign_flip_perm_p"] == 1.0
    assert inf["wilcoxon_signed_rank_p"] == 1.0


def test_zero_comments_zero_forbidden_chars_and_no_mole_ids() -> None:
    test_src = TEST_PATH.read_text(encoding="utf-8")
    assert HASH_CHAR not in test_src, f"Found hash char in {TEST_PATH}"

    for py_path in (SCRIPT_PATH, TEST_PATH):
        raw_bytes = py_path.read_bytes()
        comments = [t for t in tokenize.tokenize(io.BytesIO(raw_bytes).readline) if t.type == tokenize.COMMENT]
        assert comments == [], f"Found comment tokens in {py_path}: {comments}"

    for path in (SCRIPT_PATH, TEST_PATH, JSON_PATH, MD_PATH):
        text = path.read_text(encoding="utf-8")
        assert all(ord(ch) < 128 for ch in text), f"Found non-ASCII char in {path}"
        assert EN_DASH not in text
        assert EM_DASH not in text
        assert PLUS_MINUS not in text
        assert CO_AUTHORED_TAG not in text

    for path in (TEST_PATH, JSON_PATH, MD_PATH):
        text = path.read_text(encoding="utf-8")
        assert re.search(r"\be(?:0[1-9]|[1-3][0-9]|40)\b", text) is None
