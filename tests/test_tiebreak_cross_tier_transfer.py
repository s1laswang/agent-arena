from __future__ import annotations

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

import scripts.tiebreak_cross_tier_transfer_audit as tctta

_IMPORT_DELTA_HEAVY = (
    frozenset(m for m in ("torch", "transformers") if m in sys.modules) - _BEFORE_IMPORT_HEAVY
)

SCRIPT_PATH = REPO_ROOT / "scripts" / "tiebreak_cross_tier_transfer_audit.py"
SUMMARY_PATH = (
    REPO_ROOT / "results" / "tiebreak" / "cross_tier_transfer" / "cross_tier_transfer_summary.json"
)
REPORT_PATH = REPO_ROOT / "docs" / "reports" / "tiebreak_cross_tier_transfer.md"
SELF_PATH = Path(__file__).resolve()


def test_source_hygiene_and_cross_test_safe_ast_isolation() -> None:
    hash_char = chr(35)
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    unicode_minus = chr(0x2212)

    for py_path in (SCRIPT_PATH, SELF_PATH):
        errs = tctta.check_python_source_hygiene(py_path, full_tokenize=(py_path == SELF_PATH))
        assert errs == [], errs
        src = py_path.read_text(encoding="utf-8")
        assert hash_char not in src
        assert em_dash not in src
        assert en_dash not in src
        assert unicode_minus not in src
        assert src.isascii()

    assert _IMPORT_DELTA_HEAVY == frozenset()

    import scripts.verify_tiebreak_submission as vts

    ast_errs, checked_list = vts._audit_policy_module_ast(
        "scripts/tiebreak_cross_tier_transfer_audit.py",
        SCRIPT_PATH,
    )
    assert ast_errs == []
    assert "scripts/tiebreak_cross_tier_transfer_audit.py:ScalingLogisticPolicy" in set(checked_list)


def test_check_cli_json_mode_and_scientific_transfer_invariants(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert SUMMARY_PATH.is_file()
    assert REPORT_PATH.is_file()
    assert not (SUMMARY_PATH.parent / "summary.json").exists()
    assert not (SUMMARY_PATH.parent / "table.md").exists()

    raw_bytes = SUMMARY_PATH.read_bytes()
    assert len(raw_bytes) < 100 * 1024
    assert len(raw_bytes) < tctta.MAX_SUMMARY_BYTES

    t0 = time.perf_counter()
    rc_human = tctta.main(["--check"])
    dt = time.perf_counter() - t0
    out_human = capsys.readouterr().out
    assert rc_human == 0
    assert dt < 5.0
    assert "OK: verified" in out_human
    assert "1140/1140" in out_human

    rc_json = tctta.main(["--check", "--json"])
    verdict = json.loads(capsys.readouterr().out)
    assert rc_json == 0
    assert verdict["schema"] == tctta.SCHEMA_VERSION
    assert verdict["passed"] is True
    assert verdict["errors"] == []
    assert verdict["elapsed_seconds"] < 5.0

    assert tctta.verify_artifacts(REPO_ROOT) == {"passed": True, "errors": []}

    raw_json = raw_bytes.decode("utf-8")
    summary = json.loads(raw_json)
    md_txt = REPORT_PATH.read_text(encoding="utf-8")
    assert md_txt == tctta.render_markdown_report(summary)
    assert tctta._scan_json_for_judge_numbers(summary, raw_json) == []
    for tok_match in re.finditer(r"\b\d+\b", raw_json):
        assert int(tok_match.group(0)) < 900_000

    assert summary["world_secret_tag"] == "sha256:ebf2f09716cf76d3"
    assert summary["heldout_seed_range"] == "800000..800029"
    assert summary["eval_seed_range"] == "800000..800029"
    assert summary["eval_seeds_per_tier"] == 30
    assert summary["replay_verified"] is True
    assert summary["invalid_episodes"] == 0

    iso = summary["seed_isolation"]
    assert iso["judge_episodes_touched"] == 0
    assert iso["dev_episodes_rolled_out"] == 0
    assert iso["train_episodes_in_heldout_eval"] == 0
    assert "post-hoc locked, not pre-registered" in iso["panel_fix_a_disclosure"]

    pe = summary["panel_fix_e_track_separation"]
    assert pe["open_weight_qwen25_runs_total"] == 19
    assert pe["open_weight_qwen25_runs_above_zero"] == 0
    assert pe["open_weight_qwen25_above_zero_ratio"] == "0 / 19"
    assert pe["readme_qwen_addendum_status"] == "HOLD_README_QWEN_ADDENDUM_UNTIL_V100"
    assert pe["non_llm_policies_is_open_weight_llm"] is False

    totals = summary["totals"]
    assert totals["policy_families_audited"] == 2
    assert totals["train_regimes_per_family"] == 4
    assert totals["primary_transfer_cells"] == 24
    assert totals["total_episodes_evaluated"] == 1140
    assert totals["total_replay_verified_episodes"] == 1140
    assert totals["solver_policy_invocations"] == 0
    assert totals["api_calls"] == 0

    tm = summary["transfer_matrices"]
    eb_regs = tm["empirical_bayes"]["regimes"]
    sl_regs = tm["scaling_logistic"]["regimes"]
    assert tm["empirical_bayes"]["policy_class"] == "EmpiricalBayesPolicy"
    assert tm["empirical_bayes"]["param_count"] == 11
    assert tm["empirical_bayes"]["is_open_weight_llm"] is False
    assert tm["scaling_logistic"]["policy_class"] == "ScalingLogisticPolicy"
    assert tm["scaling_logistic"]["param_count"] == 82
    assert tm["scaling_logistic"]["is_open_weight_llm"] is False

    for regs in (eb_regs, sl_regs):
        for reg_id in ("easy_only", "medium_only", "hard_only", "pooled_all"):
            assert regs[reg_id]["is_open_weight_llm"] is False
            assert regs[reg_id]["episodes_trained"] == 270
            assert regs[reg_id]["overall_metrics"]["n"] == 90
            assert regs[reg_id]["paired_vs_before_overall"]["ci95_low"] > 0.0

    ood = summary["ood_retention_and_noise_decomposition"]
    ret = ood["zero_shot_hard_retention"]
    assert eb_regs["medium_only"]["by_tier"]["hard"]["correct_count"] == 30
    assert eb_regs["medium_only"]["by_tier"]["hard"]["wrong_count"] == 0
    assert ret["empirical_bayes_medium_to_hard"]["score_retention_vs_in_dist_pct"] > 120.0
    assert sl_regs["medium_only"]["by_tier"]["hard"]["correct_count"] == 30
    assert sl_regs["medium_only"]["by_tier"]["hard"]["wrong_count"] == 0
    assert ret["scaling_logistic_medium_to_hard"]["score_retention_vs_in_dist_pct"] > 85.0
    assert sl_regs["easy_only"]["by_tier"]["hard"]["mean_score"] > 0.25
    assert sl_regs["pooled_all"]["overall_metrics"]["mean_score"] > 0.62
    assert sl_regs["pooled_all"]["overall_metrics"]["wrong_count"] == 0

    assert eb_regs["easy_only"]["angry_messages_observed_total"] == 0
    assert eb_regs["easy_only"]["learned_params"]["w_angry_msg"] > 2.0
    assert eb_regs["easy_only"]["by_tier"]["hard"]["mean_score"] < -0.50

    surg = ood["frozen_v14_hard_surgical_arms"]
    surg_c = ood["frozen_v14_hard_contrasts"]
    assert surg["eb_easy_deception_neutral_hard_elim"]["metrics"]["mean_score"] > 0.35
    assert surg_c["eb_easy_deception_neutral_vs_raw_easy"]["ci95_low"] > 0.50
    assert surg["eb_easy_deception_neutral_fp95_cal"]["metrics"]["correct_count"] == 28
    assert surg_c["sl_easy_noise_blind_minus_header_aware"]["ci95_low"] > 0.0

    nshock = ood["hard_fingerprint_noise_counterfactual"]["arms"]
    eb_easy_shock = nshock["eb_easy_deception_neutral_hard_elim"]
    assert eb_easy_shock["fp100_noise_free_metrics"]["correct_count"] == 30
    assert eb_easy_shock["noise_shock_fp095_minus_fp100"]["mean_score_delta"] < -0.20
    assert eb_easy_shock["noise_shock_fp095_minus_fp100"]["ci95_high"] < 0.0


def test_shallow_ci_gitless_archive_and_tamper_guards(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    no_git_root = tmp_path / "unzipped_judge_export"
    for rel in (
        "results/tiebreak/cross_tier_transfer/cross_tier_transfer_summary.json",
        "docs/reports/tiebreak_cross_tier_transfer.md",
        "results/tiebreak/experiment_ledger.json",
    ):
        dst = no_git_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / rel, dst)

    assert not (no_git_root / ".git").exists()
    monkeypatch.setenv("PATH", "")

    t0 = time.perf_counter()
    assert tctta.main(["--check", "--repo-root", str(no_git_root)]) == 0
    assert time.perf_counter() - t0 < 5.0
    _ = capsys.readouterr()

    t1 = time.perf_counter()
    assert tctta.main(["--check", "--root", str(no_git_root)]) == 0
    assert time.perf_counter() - t1 < 5.0
    _ = capsys.readouterr()

    shallow_root = tmp_path / "shallow_detached_ci"
    shutil.copytree(no_git_root, shallow_root)
    (shallow_root / "results" / "tiebreak" / "experiment_ledger.json").unlink()
    (shallow_root / ".git").mkdir()
    (shallow_root / ".git" / "shallow").write_text("47888e4f\n", encoding="utf-8")
    (shallow_root / ".git" / "HEAD").write_text("47888e4f\n", encoding="utf-8")
    assert tctta.main(["--check", "--repo-root", str(shallow_root)]) == 0
    _ = capsys.readouterr()

    for bad_sib_name in ("summary.json", "table.md"):
        forbidden_sib = shallow_root / "results" / "tiebreak" / "cross_tier_transfer" / bad_sib_name
        forbidden_sib.write_text("x\n", encoding="utf-8")
        assert tctta.main(["--check", "--repo-root", str(shallow_root)]) == 1
        assert "forbidden sibling" in capsys.readouterr().err
        forbidden_sib.unlink()

    md_copy = shallow_root / "docs" / "reports" / "tiebreak_cross_tier_transfer.md"
    orig_md = md_copy.read_text(encoding="utf-8")
    md_copy.write_text(orig_md + "\nPre-registered seeds 0..29 claim.\n", encoding="utf-8")
    assert tctta.main(["--check", "--repo-root", str(shallow_root)]) == 1
    assert "Panel Fix A" in capsys.readouterr().err

    md_copy.write_text(orig_md + "\nBad " + chr(0x2014) + " dash.\n", encoding="utf-8")
    assert tctta.main(["--check", "--repo-root", str(shallow_root)]) == 1
    assert "em dash" in capsys.readouterr().err
    md_copy.write_text(orig_md, encoding="utf-8")

    json_copy = (
        shallow_root / "results" / "tiebreak" / "cross_tier_transfer" / "cross_tier_transfer_summary.json"
    )
    orig_json_txt = json_copy.read_text(encoding="utf-8")
    bad_judge = json.loads(orig_json_txt)
    bad_judge["leaked_judge_seed"] = 900_000
    json_copy.write_text(json.dumps(bad_judge, indent=2) + "\n", encoding="utf-8")
    assert tctta.main(["--check", "--repo-root", str(shallow_root)]) == 1
    assert "900000" in capsys.readouterr().err

    tampered = json.loads(orig_json_txt)
    tampered["transfer_matrices"]["empirical_bayes"]["regimes"]["easy_only"]["by_tier"]["easy"]["mean_score"] = 0.12345
    json_copy.write_text(json.dumps(tampered, indent=2) + "\n", encoding="utf-8")
    assert tctta.main(["--check", "--repo-root", str(shallow_root)]) == 1
    assert "mismatch" in capsys.readouterr().err


def test_digest_codec_seed_isolation_and_live_paired_spot_replays() -> None:
    from canary.text.template import TemplateProvider

    sample_digests = [
        f"{800_000 + i}:{'c' if i % 2 == 0 else 'a'}:{4 + (i % 5)}:{20 + i}:0.7500:3:0.9650:0.6800"
        for i in range(30)
    ]
    packed = tctta.pack_episode_digests(sample_digests)
    assert tctta.unpack_episode_digests(packed) == sample_digests

    with pytest.raises(ValueError):
        tctta.assert_strict_train_seeds([0], "dev_leak")
    with pytest.raises(ValueError):
        tctta.assert_strict_train_seeds([800_000], "heldout_leak")
    with pytest.raises(ValueError):
        tctta.assert_strict_train_seeds([900_000], "judge_leak")

    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    bundle = tctta.load_trained_bundle_from_summary(summary)
    provider = TemplateProvider()

    spot_cases = (
        ("eb:medium_only", "easy", summary["transfer_matrices"]["empirical_bayes"]["regimes"]["medium_only"]["episode_digests_packed"]["easy"]),
        ("sl:pooled_all", "easy", summary["transfer_matrices"]["scaling_logistic"]["regimes"]["pooled_all"]["episode_digests_packed"]["easy"]),
        (
            "eb:eb_easy_deception_neutral_fp95_cal",
            "hard",
            summary["ood_retention_and_noise_decomposition"]["frozen_v14_hard_surgical_arms"][
                "eb_easy_deception_neutral_fp95_cal"
            ]["episode_digests_packed"],
        ),
    )
    with tctta._scoped_world_secret(tctta.HELDOUT_WORLD_SECRET):
        for policy_kind, tier, packed_ref in spot_cases:
            rec = tctta.execute_single_episode(
                policy_kind=policy_kind,
                tier=tier,
                seed=800_000,
                provider=provider,
                bundle=bundle,
                verify_replay=True,
            )
            assert rec["replay_ok"] is True
            assert rec["digest"] == tctta.unpack_episode_digests(packed_ref)[0]
