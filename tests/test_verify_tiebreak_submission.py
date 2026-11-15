from __future__ import annotations

import ast
import io
import json
import shutil
import subprocess
import sys
import time
import tokenize
from pathlib import Path

import pytest

import scripts.verify_tiebreak_submission as gate

REPO_ROOT = Path(__file__).resolve().parents[1]
VERIFIER_PATH = REPO_ROOT / "scripts" / "verify_tiebreak_submission.py"
SELF_PATH = Path(__file__).resolve()


def _clone_tiebreak_surface(dst_root: Path) -> Path:
    rel_files = [
        ".github/protected-paths.txt",
        "docs/reports/tiebreak_small_model.md",
        "train/compact_render.py",
        "train/eval_compact_hf.py",
        "train/empirical_bayes_policy.py",
        "scripts/tiebreak_scaling_calibration.py",
        "scripts/verify_tiebreak_submission.py",
    ]
    for rel in rel_files:
        src = REPO_ROOT / rel
        target = dst_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)

    shutil.copytree(REPO_ROOT / "results" / "tiebreak", dst_root / "results" / "tiebreak")
    return dst_root


def test_verifier_and_test_source_hygiene() -> None:
    hash_char = chr(35)
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    forbidden_roots = {"torch", "transformers"}

    for path in (VERIFIER_PATH, SELF_PATH):
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(path))
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

    assert "torch" not in sys.modules
    assert "transformers" not in sys.modules


def test_live_repo_passes_all_checks_and_cli(capsys: pytest.CaptureFixture[str]) -> None:
    t0 = time.perf_counter()
    report = gate.run_all_checks(root=REPO_ROOT, strict=True)
    elapsed = time.perf_counter() - t0

    assert report["passed"] is True
    assert report["checks_passed"] == 5
    assert report["checks_total"] == 5
    assert elapsed < 3.0
    for name in gate.CHECK_NAMES:
        assert report["checks"][name]["passed"] is True
        assert report["checks"][name]["errors"] == []

    rc_std = gate.main(["--root", str(REPO_ROOT)])
    assert rc_std == 0
    human_out = capsys.readouterr().out
    assert "TIEBREAK SUBMISSION GATE [STANDARD]: PASS" in human_out

    rc_json = gate.main(["--root", str(REPO_ROOT), "--json", "--strict"])
    assert rc_json == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["passed"] is True
    assert parsed["strict"] is True
    assert set(parsed["checks"].keys()) == set(gate.CHECK_NAMES)


def test_check1_protected_and_frozen_paths_rejections(tmp_path: Path) -> None:
    syn = _clone_tiebreak_surface(tmp_path)

    clean_paths = [
        "docs/reports/tiebreak_small_model.md",
        "results/tiebreak/experiment_ledger.json",
        "scripts/verify_tiebreak_submission.py",
        "tests/test_verify_tiebreak_submission.py",
        "train/empirical_bayes_policy.py",
    ]
    ok_res = gate.check_protected_and_frozen_paths(root=syn, changed_paths=clean_paths, strict=True)
    assert ok_res.passed is True

    bad_protected = [
        "canary/env.py",
        "canary/rules.py",
        "canary/solver/policy.py",
        "harbor/build.py",
        "Makefile",
        "configs/tiers.yaml",
        "data/runs/committed/v1.4/episodes.jsonl",
        "results/judge_table.md",
        ".github/protected-paths.txt",
        ".github/workflows/guard.yml",
    ]
    for bad in bad_protected:
        res = gate.check_protected_and_frozen_paths(root=syn, changed_paths=[*clean_paths, bad])
        assert res.passed is False, f"expected protected rejection for {bad}"
        assert any("protected path touched" in e for e in res.errors)

    bad_frozen = [
        "README.md",
        "docs/SUBMISSION.md",
        "docs/reports/fr8.md",
        "docs/reports/gap.md",
        "docs/gemini/SUBMISSION.md",
    ]
    for bad in bad_frozen:
        res = gate.check_protected_and_frozen_paths(root=syn, changed_paths=[*clean_paths, bad])
        assert res.passed is False, f"expected frozen Silas doc rejection for {bad}"
        assert any("frozen Silas doc touched" in e for e in res.errors)


def test_check1_git_diff_against_base_branch_and_dirty_tree(tmp_path: Path) -> None:
    repo = tmp_path / "mini_repo"
    _clone_tiebreak_surface(repo)
    (repo / "README.md").write_text("Silas baseline\n", encoding="utf-8")

    git_env = {
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
        "PATH": "/usr/bin:/bin",
    }
    subprocess.run(["git", "init", "-b", "justSilas"], cwd=repo, env=git_env, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=repo, env=git_env, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, env=git_env, check=True, capture_output=True)

    subprocess.run(["git", "checkout", "-b", "tiebreak-test"], cwd=repo, env=git_env, check=True, capture_output=True)
    (repo / "results" / "tiebreak" / "note.txt").write_text("allowed\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, env=git_env, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "tiebreak ok"], cwd=repo, env=git_env, check=True, capture_output=True)

    ok_res = gate.check_protected_and_frozen_paths(root=repo, base_ref="justSilas")
    assert ok_res.passed is True

    (repo / "README.md").write_text("unauthorized dirty edit\n", encoding="utf-8")
    dirty_res = gate.check_protected_and_frozen_paths(root=repo, base_ref="justSilas")
    assert dirty_res.passed is False
    assert any("README.md" in e for e in dirty_res.errors)


def test_check2_ast_inference_isolation_optional_pass_and_leak_rejections(tmp_path: Path) -> None:
    syn = _clone_tiebreak_surface(tmp_path)

    clean_optional = syn / "train" / "neural_mlp_tiebreak.py"
    clean_optional.write_text(
        "class TinyMLPPolicy:\n"
        "    def reset(self, tools_spec, instruction):\n"
        "        self.ready = True\n"
        "    def belief(self):\n"
        "        return {'e00': 0.5}\n"
        "    def act(self, history):\n"
        "        _ = self.belief()\n"
        "        return ('status', {})\n",
        encoding="utf-8",
    )
    ok_res = gate.check_ast_inference_isolation(root=syn, strict=True)
    assert ok_res.passed is True
    assert "train/neural_mlp_tiebreak.py:TinyMLPPolicy" in ok_res.metrics["policy_classes_checked"]

    leak_snippets = [
        (
            "world_import_in_act",
            "class BadPolicy:\n"
            "    def reset(self, tools_spec, instruction): pass\n"
            "    def act(self, history):\n"
            "        from canary.world import generate_world\n"
            "        return ('status', {})\n",
        ),
        (
            "solver_act_in_helper",
            "from canary.solver.policy import SolverPolicy\n"
            "def _cheat_step(h):\n"
            "    return SolverPolicy().act(h)\n"
            "class BadPolicy:\n"
            "    def reset(self, tools_spec, instruction): pass\n"
            "    def act(self, history):\n"
            "        return _cheat_step(history)\n",
        ),
        (
            "solver_belief_via_helper_class",
            "class _SneakyHelper:\n"
            "    def probe(self, sp):\n"
            "        return sp.belief()\n"
            "class BadPolicy:\n"
            "    def reset(self, tools_spec, instruction):\n"
            "        self.h = _SneakyHelper()\n"
            "    def act(self, history):\n"
            "        return ('status', {})\n",
        ),
        (
            "private_world_attr_snoop",
            "class BadPolicy:\n"
            "    def reset(self, tools_spec, instruction): pass\n"
            "    def act(self, history):\n"
            "        mole = history[0]._world.mole\n"
            "        return ('accuse', {'employee': mole})\n",
        ),
        (
            "dynamic_import_leak",
            "import importlib\n"
            "class BadPolicy:\n"
            "    def reset(self, tools_spec, instruction): pass\n"
            "    def act(self, history):\n"
            "        mod = importlib.import_module('canary.world')\n"
            "        return ('status', {})\n",
        ),
        (
            "injected_oracle_act_delegation",
            "class BadPolicy:\n"
            "    def __init__(self, oracle):\n"
            "        self.oracle = oracle\n"
            "    def reset(self, tools_spec, instruction): pass\n"
            "    def act(self, history):\n"
            "        return self.oracle.act(history)\n",
        ),
    ]
    for label, bad_code in leak_snippets:
        clean_optional.write_text(bad_code, encoding="utf-8")
        res = gate.check_ast_inference_isolation(root=syn, strict=True)
        assert res.passed is False, f"expected AST leak rejection for {label}"
        assert len(res.errors) >= 1


def test_check3_seed_and_secret_provenance_tamper_rejections(tmp_path: Path) -> None:
    syn = _clone_tiebreak_surface(tmp_path)
    assert gate.check_seed_and_secret_provenance(root=syn, strict=True).passed is True

    eb_summary_path = syn / "results" / "tiebreak" / "empirical_bayes" / "summary.json"
    orig_eb = json.loads(eb_summary_path.read_text(encoding="utf-8"))

    bad_train = json.loads(json.dumps(orig_eb))
    bad_train["train_seeds"] = {"start": 500, "stop": 530}
    eb_summary_path.write_text(json.dumps(bad_train), encoding="utf-8")
    res_tr = gate.check_seed_and_secret_provenance(root=syn)
    assert res_tr.passed is False
    assert any("train_seed" in e for e in res_tr.errors)

    bad_eval = json.loads(json.dumps(orig_eb))
    bad_eval["eval_seeds"] = {"start": 800190, "stop": 800210}
    eb_summary_path.write_text(json.dumps(bad_eval), encoding="utf-8")
    res_ev = gate.check_seed_and_secret_provenance(root=syn)
    assert res_ev.passed is False
    assert any("held-out eval_seed" in e for e in res_ev.errors)

    bad_judge = json.loads(json.dumps(orig_eb))
    bad_judge["eval_seeds"] = [900000, 900001]
    eb_summary_path.write_text(json.dumps(bad_judge), encoding="utf-8")
    res_jg = gate.check_seed_and_secret_provenance(root=syn)
    assert res_jg.passed is False
    assert any("JUDGE_SEEDS" in e for e in res_jg.errors)

    eb_summary_path.write_text(json.dumps(orig_eb), encoding="utf-8")
    assert gate.check_seed_and_secret_provenance(root=syn).passed is True

    ledger_path = syn / "results" / "tiebreak" / "experiment_ledger.json"
    orig_ledger = json.loads(ledger_path.read_text(encoding="utf-8"))

    for tamper_fn, expected_substr in (
        (lambda d: d["discovered_runs"][0].update({"heldout_n": 20}), "n >= 30"),
        (
            lambda d: d["discovered_runs"][0].update({"after_world_secret_tag": "sha256:deadbeef00001111"}),
            "world_secret_tag mismatch",
        ),
        (lambda d: d["discovered_runs"][0].update({"before_world_secret_tag": "unset"}), "world_secret_tag"),
        (lambda d: d["discovered_runs"][0].update({"replay_verified": False}), "replay_verified"),
        (lambda d: d["discovered_runs"][0].update({"paired_ci95_low": 0.0}), "paired_ci95_low > 0.0"),
    ):
        mut = json.loads(json.dumps(orig_ledger))
        tamper_fn(mut)
        ledger_path.write_text(json.dumps(mut), encoding="utf-8")
        res_l = gate.check_seed_and_secret_provenance(root=syn)
        assert res_l.passed is False
        assert any(expected_substr in e for e in res_l.errors), res_l.errors

    ledger_path.write_text(json.dumps(orig_ledger), encoding="utf-8")
    spoof_eb = json.loads(json.dumps(orig_eb))
    spoof_eb["paired"]["deltas"] = [-0.2] * 90
    eb_summary_path.write_text(json.dumps(spoof_eb), encoding="utf-8")
    res_spoof = gate.check_seed_and_secret_provenance(root=syn)
    assert res_spoof.passed is False
    assert any("recomputed paired ci95_low" in e for e in res_spoof.errors)


def test_check4_claim_number_audit_tamper_rejections(tmp_path: Path) -> None:
    syn = _clone_tiebreak_surface(tmp_path)
    assert gate.check_claim_number_audit(root=syn, strict=True).passed is True

    report_path = syn / "docs" / "reports" / "tiebreak_small_model.md"
    orig_report = report_path.read_text(encoding="utf-8")
    report_path.write_text(
        orig_report.replace(
            "Verified improvements passing all 4 strict gates: `1`",
            "Verified improvements passing all 4 strict gates: `3`",
        ),
        encoding="utf-8",
    )
    res_r = gate.check_claim_number_audit(root=syn)
    assert res_r.passed is False
    assert any("verified_improvements" in e for e in res_r.errors)
    report_path.write_text(orig_report, encoding="utf-8")

    sc_table_path = syn / "results" / "tiebreak" / "scaling" / "table.md"
    orig_sc_table = sc_table_path.read_text(encoding="utf-8")
    sc_table_path.write_text(orig_sc_table.replace("+0.611 +/- 0.069", "+0.755 +/- 0.069"), encoding="utf-8")
    res_sc = gate.check_claim_number_audit(root=syn)
    assert res_sc.passed is False
    assert any("scaling/table.md" in e for e in res_sc.errors)
    sc_table_path.write_text(orig_sc_table, encoding="utf-8")

    eb_table_path = syn / "results" / "tiebreak" / "empirical_bayes" / "table.md"
    orig_eb_table = eb_table_path.read_text(encoding="utf-8")
    eb_table_path.write_text(orig_eb_table.replace("+0.622 [+0.571, +0.671]", "+0.822 [+0.571, +0.671]"), encoding="utf-8")
    res_eb = gate.check_claim_number_audit(root=syn)
    assert res_eb.passed is False
    assert any("empirical_bayes/table.md" in e for e in res_eb.errors)
    eb_table_path.write_text(orig_eb_table, encoding="utf-8")

    orphan_dir = syn / "results" / "tiebreak" / "unbacked_run"
    orphan_dir.mkdir(parents=True, exist_ok=True)
    (orphan_dir / "table.md").write_text("| metric | val |\n|---|---:|\n| score | 0.500 |\n", encoding="utf-8")
    res_orphan = gate.check_claim_number_audit(root=syn)
    assert res_orphan.passed is False
    assert any("missing backing summary.json" in e for e in res_orphan.errors)

    (orphan_dir / "summary.json").write_text(
        json.dumps({"before": {"mean_score": 0.100}, "after": {"mean_score": 0.900}, "paired": {"mean_delta": 0.800, "ci95_low": 0.600}}),
        encoding="utf-8",
    )
    res_mismatch = gate.check_claim_number_audit(root=syn)
    assert res_mismatch.passed is False
    assert any("not found in markdown table" in e for e in res_mismatch.errors)


def test_check5_hygiene_and_panel_fix_a_tamper_rejections(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    syn = _clone_tiebreak_surface(tmp_path)
    assert gate.check_hygiene_and_panel_fix_a(root=syn, tracked_paths=[], strict=True).passed is True

    report_path = syn / "docs" / "reports" / "tiebreak_small_model.md"
    orig_report = report_path.read_text(encoding="utf-8")

    honest_note = "\nDev seeds 0-29 are a post-hoc lock, not a pre-registration.\n"
    report_path.write_text(orig_report + honest_note, encoding="utf-8")
    assert gate.check_hygiene_and_panel_fix_a(root=syn, tracked_paths=[], strict=True).passed is True

    report_path.write_text(orig_report + f"\nBad punctuation {chr(0x2014)} here.\n", encoding="utf-8")
    res_em = gate.check_hygiene_and_panel_fix_a(root=syn, tracked_paths=[])
    assert res_em.passed is False
    assert any("em dash" in e for e in res_em.errors)

    report_path.write_text(orig_report + f"\nRange 10{chr(0x2013)}20 with en dash.\n", encoding="utf-8")
    res_en_std = gate.check_hygiene_and_panel_fix_a(root=syn, tracked_paths=[], strict=False)
    assert res_en_std.passed is True
    assert len(res_en_std.warnings) == 1
    res_en_strict = gate.check_hygiene_and_panel_fix_a(root=syn, tracked_paths=[], strict=True)
    assert res_en_strict.passed is False

    report_path.write_text(orig_report + "\nEvaluated on our pre-registered seeds 0-29 split.\n", encoding="utf-8")
    res_prereg = gate.check_hygiene_and_panel_fix_a(root=syn, tracked_paths=[])
    assert res_prereg.passed is False
    assert any("Panel Fix A" in e for e in res_prereg.errors)
    report_path.write_text(orig_report, encoding="utf-8")

    bad_wt = syn / "train" / "adapter_model.safetensors"
    bad_wt.write_bytes(b"weights")
    res_wt = gate.check_hygiene_and_panel_fix_a(root=syn, tracked_paths=["train/adapter_model.safetensors"])
    assert res_wt.passed is False
    assert any(".safetensors" in e for e in res_wt.errors)
    bad_wt.unlink()

    big_dump = syn / "results" / "tiebreak" / "huge_dump.json"
    with open(big_dump, "wb") as fh:
        fh.seek(gate.MAX_FILE_BYTES + 64)
        fh.write(b"\0")
    res_big = gate.check_hygiene_and_panel_fix_a(root=syn, tracked_paths=[])
    assert res_big.passed is False
    assert any("oversized file" in e for e in res_big.errors)

    rc_fail = gate.main(["--root", str(syn), "--json"])
    assert rc_fail == 1
    fail_json = json.loads(capsys.readouterr().out)
    assert fail_json["passed"] is False
    assert fail_json["checks"]["hygiene_and_panel_fix_a"]["passed"] is False
