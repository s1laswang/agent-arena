from __future__ import annotations

import ast
import json
from pathlib import Path
import re
import shutil
import sys
import time

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_BEFORE_IMPORT_HEAVY = frozenset(m for m in ("torch", "transformers") if m in sys.modules)
_BEFORE_IMPORT_SOLVER = frozenset(
    m for m in sys.modules if m == "canary.solver" or m.startswith("canary.solver.")
)
_BEFORE_IMPORT_WORLD = frozenset(
    m for m in sys.modules if m == "canary.world" or m.startswith("canary.world.")
)

import scripts.tiebreak_statistical_power_audit as tspa

_IMPORT_DELTA_HEAVY = (
    frozenset(m for m in ("torch", "transformers") if m in sys.modules) - _BEFORE_IMPORT_HEAVY
)
_IMPORT_DELTA_SOLVER = (
    frozenset(m for m in sys.modules if m == "canary.solver" or m.startswith("canary.solver."))
    - _BEFORE_IMPORT_SOLVER
)
_IMPORT_DELTA_WORLD = (
    frozenset(m for m in sys.modules if m == "canary.world" or m.startswith("canary.world."))
    - _BEFORE_IMPORT_WORLD
)

SCRIPT_PATH = REPO_ROOT / "scripts" / "tiebreak_statistical_power_audit.py"
SUMMARY_PATH = REPO_ROOT / "results" / "tiebreak" / "statistical_power" / "statistical_power_summary.json"
REPORT_PATH = REPO_ROOT / "docs" / "reports" / "tiebreak_statistical_power.md"
SELF_PATH = Path(__file__).resolve()


def test_source_hygiene_and_ast_isolation() -> None:
    t0 = time.perf_counter()
    hash_char = chr(35)
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    unicode_minus = chr(0x2212)
    forbidden_roots = {"torch", "transformers", "subprocess"}

    for py_path in (SCRIPT_PATH, SELF_PATH):
        errs = tspa.check_python_source_hygiene(py_path, run_tokenize=(py_path == SELF_PATH))
        assert errs == [], errs
        src = py_path.read_text(encoding="utf-8")
        assert hash_char not in src
        assert em_dash not in src
        assert en_dash not in src
        assert unicode_minus not in src
        assert src.isascii()

    for py_path in (SCRIPT_PATH, SELF_PATH):
        tree = ast.parse(py_path.read_text(encoding="utf-8"), filename=str(py_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] not in forbidden_roots
                    assert not alias.name.startswith(("canary.solver", "canary.world"))
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in forbidden_roots
                assert not node.module.startswith(("canary.solver", "canary.world"))
                if node.module == "canary":
                    imported = {a.name for a in node.names}
                    assert "solver" not in imported
                    assert "world" not in imported

    assert _IMPORT_DELTA_HEAVY == frozenset()
    assert _IMPORT_DELTA_SOLVER == frozenset()
    assert _IMPORT_DELTA_WORLD == frozenset()
    assert (time.perf_counter() - t0) < 10.0


def test_check_cli_json_mode_and_scientific_invariants(capsys: pytest.CaptureFixture[str]) -> None:
    t_wall = time.perf_counter()
    assert SUMMARY_PATH.is_file()
    assert REPORT_PATH.is_file()
    assert not (SUMMARY_PATH.parent / "summary.json").exists()
    assert not (SUMMARY_PATH.parent / "table.md").exists()

    raw_bytes = SUMMARY_PATH.read_bytes()
    assert len(raw_bytes) < tspa.MAX_SUMMARY_BYTES
    assert len(raw_bytes) < 75 * 1024

    t0 = time.perf_counter()
    rc_human = tspa.main(["--check"])
    dt_check = time.perf_counter() - t0
    out_human = capsys.readouterr().out
    assert rc_human == 0
    assert dt_check < 10.0
    assert "OK: verified 8 primary + 12 expanded" in out_human
    assert "9/9 world-paired N_eff>1" in out_human
    assert "540/540 replays" in out_human

    rc_json = tspa.main(["--check", "--json"])
    verdict = json.loads(capsys.readouterr().out)
    assert rc_json == 0
    assert verdict["schema"] == tspa.SCHEMA_VERSION
    assert verdict["passed"] is True
    assert verdict["errors"] == []
    assert verdict["elapsed_seconds"] < 10.0

    raw_json = raw_bytes.decode("utf-8")
    md_txt = REPORT_PATH.read_text(encoding="utf-8")
    assert raw_json.isascii()
    assert md_txt.isascii()

    summary = json.loads(raw_json)
    assert md_txt == tspa.render_markdown_report(summary)
    assert tspa._scan_json_for_judge_numbers(summary, raw_json) == []
    for tok_match in re.finditer(r"\b\d{6,}\b", raw_json):
        prefix2 = raw_json[max(0, tok_match.start() - 2) : tok_match.start()]
        if prefix2.lower() != "0x":
            assert int(tok_match.group(0)) < 900_000

    assert summary["world_secret_tag"] == "sha256:ebf2f09716cf76d3"
    assert summary["verda_shared_secret_tag"] == "verda_shared_secret_0405_1ca0c2a64d"
    assert summary["replay_verified"] is True
    assert summary["invalid_episodes"] == 0

    iso = summary["seed_isolation"]
    assert iso["train_seed_partition"] == "[100000, 200000)"
    assert iso["heldout_seed_partition"] == "[800000, 800200)"
    assert iso["judge_episodes_touched"] == 0
    assert iso["dev_episodes_touched"] == 0
    assert "post-hoc locked, not pre-registered" in iso["panel_fix_a_disclosure"]

    pe = summary["panel_fix_e_track_separation"]
    assert pe["compact_policies_are_open_weight_llm"] is False
    assert pe["open_weight_qwen25_runs_total"] == 19
    assert pe["open_weight_qwen25_runs_above_zero"] == 0
    assert pe["open_weight_qwen25_above_zero_ratio"] == "0 / 19"
    assert pe["readme_qwen_addendum_status"] == "HOLD_README_QWEN_ADDENDUM_UNTIL_V100"

    totals = summary["totals"]
    assert totals["primary_family_size"] == 8
    assert totals["expanded_family_size"] == 12
    assert totals["compact_verified_positive_primary"] == 4
    assert totals["compact_verified_positive_expanded"] == 8
    assert totals["open_weight_verified_improvements_over_base"] == 0
    assert totals["heldout_pairing_pairs_with_neff_gt_1"] == 9
    assert totals["heldout_pairing_pairs_total"] == 9
    assert totals["live_canonical_env_replays_verified"] == 540

    prim = {r["comparison_id"]: r for r in summary["primary_family"]}
    for cid in (
        "empirical_bayes_vs_before",
        "compact_linear_dagger_vs_before",
        "tiny_mlp_dagger_vs_before",
        "scaling_logistic_vs_before",
    ):
        row = prim[cid]
        assert row["is_open_weight_llm"] is False
        assert row["mean_delta"] > 0.60
        assert row["bootstrap_ci95_low"] > 0.50
        assert row["p_perm_two_sided"] == pytest.approx(0.0001, abs=1e-5)
        assert row["p_holm_two_sided"] <= 0.001
        assert row["q_bh_two_sided"] <= 0.0002
        assert row["verified_positive_after_holm05"] is True

    assert prim["verda_v3_8k_s0_vs_s3"]["mean_delta"] == pytest.approx(0.7278, abs=5e-4)
    assert prim["verda_v3_8k_s0_vs_s3"]["reject_fwer05_two_sided"] is True
    assert prim["verda_4k_at_8k_vs_8k_s3_null"]["reject_fwer05_two_sided"] is False
    assert prim["verda_4k_at_8k_vs_8k_s3_null"]["p_holm_two_sided"] > 0.20
    assert prim["verda_dagger_r1_8k_vs_base"]["mean_delta"] == pytest.approx(-0.542, abs=1e-4)
    assert prim["verda_dagger_r1_8k_vs_base"]["bootstrap_ci95_high"] < -0.30
    assert prim["verda_dagger_r1_8k_vs_base"]["p_holm_gt0"] == pytest.approx(1.0, abs=1e-5)
    assert prim["verda_dagger_r1_4k_vs_base"]["mean_delta"] == pytest.approx(-0.101, abs=1e-4)
    assert prim["verda_dagger_r1_4k_vs_base"]["reject_fwer05_two_sided"] is False

    wp = summary["world_pairing_variance_reduction"]
    assert wp["heldout_mean_n_eff_ratio"] > 1.15
    assert wp["heldout_max_n_eff_ratio"] > 1.25
    for prow in wp["heldout_compact_pairs"]:
        assert prow["var_paired"] < prow["var_unpaired"]
        assert prow["pearson_r"] > 0.10
        assert prow["n_eff_ratio"] > 1.10

    mde_audit = summary["mde_audit"]
    assert mde_audit["sample_sizes"] == [30, 41, 50, 90, 180]
    mde_factors = [float(r["unit_sd_mde_factor"]) for r in mde_audit["mde_table"]]
    assert mde_factors[0] > mde_factors[1] > mde_factors[2] > mde_factors[3] > mde_factors[4]

    diag8 = mde_audit["verda_x2_dagger_r1_truncation_diagnosis"]["dagger_r1_8k"]
    diag4 = mde_audit["verda_x2_dagger_r1_truncation_diagnosis"]["dagger_r1_4k"]
    assert diag8["rules_out_positive_heldout_score"] is True
    assert diag8["abs_score_over_mde_ratio"] > 1.70
    assert diag8["paired_head_to_head_delta"] < diag8["paired_head_to_head_mde_at_n43"]
    assert diag8["required_n_for_80pct_power_at_0242"] > 120
    assert diag4["abs_score_over_mde_ratio"] < 1.0
    assert diag4["max_plausible_positive_score_ci95_high"] == pytest.approx(0.011, abs=1e-4)
    assert (time.perf_counter() - t_wall) < 10.0


def test_seeded_permutation_reproduction_and_multiplicity_math() -> None:
    t0 = time.perf_counter()
    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    prim = {r["comparison_id"]: r for r in summary["primary_family"]}

    led = json.loads((REPO_ROOT / tspa.LEDGER_REL).read_text(encoding="utf-8"))
    hmap = {r["run_id"]: r for r in led["historical_runs"]}

    dag4_vec = tspa.reconstruct_verda_dagger_vector(hmap["WS4-dagger-r1-4k-verda"])
    dag4_recomp = tspa.run_signflip_and_bootstrap(
        dag4_vec,
        n_draws=tspa.PERMUTATION_DRAWS,
        seed=tspa.PERMUTATION_SEED,
    )
    assert dag4_recomp["p_perm_two_sided"] == prim["verda_dagger_r1_4k_vs_base"]["p_perm_two_sided"]
    assert dag4_recomp["bootstrap_ci95_low"] == prim["verda_dagger_r1_4k_vs_base"]["bootstrap_ci95_low"]
    assert dag4_recomp["bootstrap_ci95_high"] == prim["verda_dagger_r1_4k_vs_base"]["bootstrap_ci95_high"]

    raw_p = [0.04, 0.001, 0.25, 0.012, 0.015]
    holm_p = tspa.holm_bonferroni_adjust(raw_p)
    bh_q = tspa.benjamini_hochberg_adjust(raw_p)
    for r_p, h_p, q_p in zip(raw_p, holm_p, bh_q):
        assert r_p <= q_p <= h_p <= 1.0
    order = sorted(range(len(raw_p)), key=lambda i: raw_p[i])
    for a, b in zip(order, order[1:]):
        assert holm_p[a] <= holm_p[b] + 1e-12
        assert bh_q[a] <= bh_q[b] + 1e-12
    assert (time.perf_counter() - t0) < 10.0


def test_shallow_ci_gitless_archive_and_tamper_guards(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    t0 = time.perf_counter()
    no_git_root = tmp_path / "unzipped_judge_export"
    for rel in (
        "results/tiebreak/statistical_power/statistical_power_summary.json",
        "docs/reports/tiebreak_statistical_power.md",
        "results/tiebreak/experiment_ledger.json",
    ):
        dst = no_git_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / rel, dst)

    assert not (no_git_root / ".git").exists()
    monkeypatch.setenv("PATH", "")

    assert tspa.main(["--check", "--repo-root", str(no_git_root)]) == 0
    _ = capsys.readouterr()

    (no_git_root / ".git").mkdir()
    (no_git_root / ".git" / "shallow").write_text("e9802f15\n", encoding="utf-8")
    (no_git_root / ".git" / "HEAD").write_text("e9802f15\n", encoding="utf-8")
    assert tspa.main(["--check", "--root", str(no_git_root)]) == 0
    _ = capsys.readouterr()

    for bad_name in ("summary.json", "table.md"):
        sib = no_git_root / "results" / "tiebreak" / "statistical_power" / bad_name
        sib.write_text("{}\n", encoding="utf-8")
        assert tspa.main(["--check", "--repo-root", str(no_git_root)]) == 1
        assert "forbidden sibling" in capsys.readouterr().err
        sib.unlink()

    md_copy = no_git_root / "docs" / "reports" / "tiebreak_statistical_power.md"
    orig_md = md_copy.read_text(encoding="utf-8")
    md_copy.write_text(
        orig_md + "\nPre-registered seeds 0..29 claim.\nBad " + chr(0x2014) + " dash.\n",
        encoding="utf-8",
    )
    assert tspa.main(["--check", "--repo-root", str(no_git_root)]) == 1
    err_md = capsys.readouterr().err
    assert "Panel Fix A" in err_md
    assert "em dash" in err_md
    md_copy.write_text(orig_md, encoding="utf-8")

    json_copy = no_git_root / "results" / "tiebreak" / "statistical_power" / "statistical_power_summary.json"
    bad_summary = json.loads(json_copy.read_text(encoding="utf-8"))
    bad_summary["leaked_judge_seed"] = 900_000
    json_copy.write_text(json.dumps(bad_summary, indent=2) + "\n", encoding="utf-8")
    assert tspa.main(["--check", "--repo-root", str(no_git_root)]) == 1
    assert "900000" in capsys.readouterr().err
    assert (time.perf_counter() - t0) < 10.0
