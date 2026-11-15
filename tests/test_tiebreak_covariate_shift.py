from __future__ import annotations

import ast
import io
import json
from pathlib import Path
import re
import shutil
import sys
import time
import tokenize

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_BEFORE_IMPORT_HEAVY = frozenset(m for m in ("torch", "transformers") if m in sys.modules)
_BEFORE_IMPORT_SOLVER = frozenset(m for m in sys.modules if m == "canary.solver" or m.startswith("canary.solver."))
_BEFORE_IMPORT_WORLD = frozenset(m for m in sys.modules if m == "canary.world" or m.startswith("canary.world."))

import scripts.tiebreak_covariate_shift_audit as tcsa

_IMPORT_DELTA_HEAVY = frozenset(m for m in ("torch", "transformers") if m in sys.modules) - _BEFORE_IMPORT_HEAVY
_IMPORT_DELTA_SOLVER = frozenset(m for m in sys.modules if m == "canary.solver" or m.startswith("canary.solver.")) - _BEFORE_IMPORT_SOLVER
_IMPORT_DELTA_WORLD = frozenset(m for m in sys.modules if m == "canary.world" or m.startswith("canary.world.")) - _BEFORE_IMPORT_WORLD

SCRIPT_PATH = REPO_ROOT / "scripts" / "tiebreak_covariate_shift_audit.py"
SUMMARY_PATH = REPO_ROOT / "results" / "tiebreak" / "covariate_shift" / "covariate_shift_summary.json"
REPORT_PATH = REPO_ROOT / "docs" / "reports" / "tiebreak_covariate_shift.md"
SELF_PATH = Path(__file__).resolve()


def test_source_hygiene_and_cross_test_safe_ast_isolation() -> None:
    hash_char = chr(35)
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    unicode_minus = chr(0x2212)
    forbidden_roots = {"torch", "transformers", "subprocess"}
    bad_s_mod = "canary." + "solver"
    bad_w_mod = "canary." + "world"

    for py_path in (SCRIPT_PATH, SELF_PATH):
        errs = tcsa.check_python_source_hygiene(py_path, run_tokenize=True)
        assert errs == [], errs
        src = py_path.read_text(encoding="utf-8")
        assert hash_char not in src
        assert em_dash not in src
        assert en_dash not in src
        assert unicode_minus not in src
        assert src.isascii()
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
        assert not [t for t in toks if t.type == tokenize.COMMENT]

        tree = ast.parse(src, filename=str(py_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] not in forbidden_roots
                    assert not alias.name.startswith((bad_s_mod, bad_w_mod))
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in forbidden_roots
                assert not node.module.startswith((bad_s_mod, bad_w_mod))
                if node.module == "canary":
                    imported = {a.name for a in node.names}
                    assert "solver" not in imported
                    assert "world" not in imported

    assert _IMPORT_DELTA_HEAVY == frozenset()
    assert _IMPORT_DELTA_SOLVER == frozenset()
    assert _IMPORT_DELTA_WORLD == frozenset()


def test_check_cli_json_mode_and_covariate_shift_invariants(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert SUMMARY_PATH.is_file()
    assert REPORT_PATH.is_file()
    assert not (SUMMARY_PATH.parent / "summary.json").exists()
    assert not (SUMMARY_PATH.parent / "table.md").exists()

    raw_bytes = SUMMARY_PATH.read_bytes()
    assert len(raw_bytes) <= tcsa.MAX_SUMMARY_BYTES
    assert len(raw_bytes) <= 70 * 1024

    t0 = time.perf_counter()
    rc_human = tcsa.main(["--check"])
    dt = time.perf_counter() - t0
    out_human = capsys.readouterr().out
    assert rc_human == 0
    assert dt < tcsa.MAX_CHECK_SECONDS
    assert "OK: verified 6 compact trajectories" in out_human
    assert "540/540 replays" in out_human

    rc_json = tcsa.main(["--check", "--json"])
    verdict = json.loads(capsys.readouterr().out)
    assert rc_json == 0
    assert verdict["schema"] == tcsa.SCHEMA_VERSION
    assert verdict["passed"] is True
    assert verdict["errors"] == []
    assert verdict["elapsed_seconds"] < tcsa.MAX_CHECK_SECONDS

    raw_json = raw_bytes.decode("utf-8")
    md_txt = REPORT_PATH.read_text(encoding="utf-8")
    assert raw_json.isascii() and md_txt.isascii()

    summary = json.loads(raw_json)
    assert md_txt == tcsa.render_markdown_report(summary)
    assert tcsa._scan_json_for_judge_numbers(summary, raw_json) == []
    for tok_match in re.finditer(r"\b\d{6,}\b", raw_json):
        prefix2 = raw_json[max(0, tok_match.start() - 2) : tok_match.start()]
        if prefix2.lower() != "0x":
            assert int(tok_match.group(0)) < tcsa.JUDGE_SEED_MIN

    assert summary["world_secret_tag"] == "sha256:ebf2f09716cf76d3"
    assert summary["heldout_seed_range"] == "800000..800029"
    assert summary["replay_verified"] is True
    assert summary["invalid_episodes"] == 0

    iso = summary["seed_isolation"]
    assert iso["judge_episodes_touched"] == 0
    assert iso["dev_episodes_touched"] == 0
    assert iso["train_episodes_in_heldout_eval"] == 0
    assert "post-hoc locked, not pre-registered" in iso["panel_fix_a_disclosure"]

    pe = summary["panel_fix_e_track_separation"]
    assert pe["is_open_weight_llm"] is False
    assert pe["compact_policies_are_open_weight_llm"] is False
    assert pe["open_weight_qwen25_above_zero_ratio"] == "0 / 19"
    assert pe["readme_qwen_addendum_status"] == "HOLD_README_QWEN_ADDENDUM_UNTIL_V100"

    ph = summary["horizon_phase_compounding"]
    assert ph["linear_offline_bc"]["compounding_late_over_early_ratio"]["smd_top1"] > 7.5
    assert ph["linear_offline_bc"]["compounding_late_over_early_ratio"]["js_top1"] > 15.0
    assert ph["mlp_r0_sft"]["compounding_late_over_early_ratio"]["smd_top1"] > 20.0
    assert ph["mlp_r0_sft"]["compounding_late_over_early_ratio"]["marg_l1_28d"] > 20.0

    drec = summary["dagger_covariate_shift_recovery"]
    assert drec["linear_bc_to_stage4_dagger_late_reduction_pct"]["js_top1"] > 85.0
    assert drec["linear_bc_to_stage4_dagger_late_reduction_pct"]["smd_top1"] > 70.0
    assert drec["mlp_r0_sft_to_r2_dagger_late_reduction_pct"]["smd_top1"] > 85.0
    assert drec["mlp_r0_sft_to_r2_dagger_late_reduction_pct"]["marg_l1_28d"] > 80.0

    rec90 = summary["paired_score_recovery"]["live_n90_world_paired"]
    assert rec90["linear_stage4_dagger_minus_offline_bc"]["bootstrap_ci95_low"] > 0.05
    assert rec90["mlp_r2_dagger_minus_r0_sft"]["bootstrap_ci95_low"] > 0.60


def test_shallow_gitless_repo_root_and_tamper_guards(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    no_git_root = tmp_path / "unzipped_judge_export"
    for rel in (tcsa.DEFAULT_OUT_JSON, tcsa.DEFAULT_OUT_MD, tcsa.LEDGER_REL):
        dst = no_git_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / rel, dst)

    assert not (no_git_root / ".git").exists()
    monkeypatch.setenv("PATH", "")

    assert tcsa.main(["--check", "--repo-root", str(no_git_root)]) == 0
    _ = capsys.readouterr()

    (no_git_root / ".git").mkdir()
    (no_git_root / ".git" / "shallow").write_text("d67809d5\n", encoding="utf-8")
    (no_git_root / ".git" / "HEAD").write_text("d67809d5\n", encoding="utf-8")
    assert tcsa.main(["--check", "--root", str(no_git_root), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["passed"] is True

    sib_dir = (no_git_root / tcsa.DEFAULT_OUT_JSON).parent
    for bad_name in ("summary.json", "table.md"):
        (sib_dir / bad_name).write_text("{}\n", encoding="utf-8")
    assert tcsa.main(["--check", "--repo-root", str(no_git_root)]) == 1
    sib_err = capsys.readouterr().err
    assert "summary.json" in sib_err and "table.md" in sib_err
    for bad_name in ("summary.json", "table.md"):
        (sib_dir / bad_name).unlink()

    md_copy = no_git_root / tcsa.DEFAULT_OUT_MD
    orig_md = md_copy.read_text(encoding="utf-8")
    md_copy.write_text(
        orig_md + "\nPre-registered seeds 0..29 claim.\nBad " + chr(0x2014) + " dash.\n",
        encoding="utf-8",
    )
    assert tcsa.main(["--check", "--repo-root", str(no_git_root)]) == 1
    err_md = capsys.readouterr().err
    assert "Panel Fix A" in err_md and "em dash" in err_md
    md_copy.write_text(orig_md, encoding="utf-8")

    json_copy = no_git_root / tcsa.DEFAULT_OUT_JSON
    bad_summary = json.loads(json_copy.read_text(encoding="utf-8"))
    bad_summary["leaked_judge_seed"] = 900_000
    bad_summary["policy_trajectories"]["linear_stage4_dagger"]["mean_score_n90"] = 0.9999
    json_copy.write_text(json.dumps(bad_summary, indent=2) + "\n", encoding="utf-8")
    assert tcsa.main(["--check", "--repo-root", str(no_git_root)]) == 1
    err_json = capsys.readouterr().err
    assert "900000" in err_json and "disagrees" in err_json


def test_live_spot_parity_and_divergence_math() -> None:
    fn_heavy = {m for m in ("torch", "transformers") if m in sys.modules}
    fn_solver = {m for m in sys.modules if m == "canary.solver" or m.startswith("canary.solver.")}

    assert tcsa.compute_smd([0.2, 0.4, 0.6], [0.2, 0.4, 0.6]) == 0.0
    assert tcsa.compute_smd([0.9, 0.95, 1.0], [0.1, 0.15, 0.2]) > 5.0
    assert tcsa.compute_binned_js_bits([0.1, 0.2], [0.1, 0.2], (0.0, 0.5, 1.0)) == pytest.approx(0.0, abs=1e-9)
    assert 0.5 < tcsa.compute_binned_js_bits([0.05, 0.1], [0.85, 0.95], (0.0, 0.5, 1.0)) <= 1.0

    from canary.env import Env
    from canary.eval import run_episode
    from canary.text.template import TemplateProvider
    import scripts.run_tiebreak_policy as rtp
    from train.compact_dagger_ablation import CompactLinearDAggerPolicy, CompactLinearWeights
    from train.empirical_bayes_policy import EmpiricalBayesParams, EmpiricalBayesPolicy

    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    eb_sum = json.loads((REPO_ROOT / tcsa.EB_SUMMARY_REL).read_text(encoding="utf-8"))
    da_sum = json.loads((REPO_ROOT / tcsa.DAGGER_SUMMARY_REL).read_text(encoding="utf-8"))
    eb_opt = EmpiricalBayesParams.from_dict(eb_sum["parameters"]["eb_experience_opt"])
    w_lin_da = CompactLinearWeights.from_dict(da_sum["learned_weights_stage3"])
    tp = TemplateProvider()

    with tcsa._scoped_world_secret(tcsa.HELDOUT_WORLD_SECRET):
        for pid, kind, wp, pol in (
            ("eb_reference", "eb", eb_opt, EmpiricalBayesPolicy(eb_opt, seed=800_000, name="eb_reference")),
            ("linear_stage4_dagger", "lin", w_lin_da, CompactLinearDAggerPolicy(w_lin_da, name="linear_stage4_dagger")),
        ):
            env = Env("easy", 800_000, text_provider=tp)
            instr = env.instruction()
            ep = run_episode(env, pol)
            assert rtp.verify_episode_replay(ep, text_provider=tp) is True
            rec = tcsa._extract_episode_daily(ep, instr, kind, wp, 14)
            spot = summary["policy_trajectories"][pid]["spot_easy_800000"]
            assert round(float(rec["score"]), 5) == pytest.approx(spot["score"], abs=1e-5)
            assert int(rec["final_day"]) == spot["final_day"] and int(rec["diag_arms"]) == spot["diag_arms"]
            assert round(float(rec["days"][7]["top1_p"]), 5) == pytest.approx(spot["day7_top1_p"], abs=1e-5)
            assert round(float(rec["days"][7]["v_obs"]), 5) == pytest.approx(spot["day7_v_obs"], abs=1e-5)

    assert ({m for m in ("torch", "transformers") if m in sys.modules} - fn_heavy) == set()
    assert ({m for m in sys.modules if m == "canary.solver" or m.startswith("canary.solver.")} - fn_solver) == set()
